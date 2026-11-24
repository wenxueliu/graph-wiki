"""Deterministic knowledge-quality assessment for a vault.

The quality report is an aggregation layer, not a second linter. It reuses
``lint_vault`` for structural and trust findings, reuses ``verify_completeness``
for manifest coverage, and adds the signals that were previously only available
to the agent-driven semantic audit: source presence, provenance coverage, and
lifecycle distribution.

The report is intentionally signal-based. It does not compute a single
"quality score"; each dimension carries its own status and counts so a CI gate
can fail on data-integrity problems without pretending to grade prose.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_wiki.knowledge_pack import iter_content_pages
from graph_wiki.lint import lint_vault
from graph_wiki.trust import TRUST_LEDGER_RELATIVE_PATH
from graph_wiki.verify import verify_completeness

RESERVED_PAGE_STEMS = frozenset({"index", "log", "hot", "_insights"})
# Mirrors the thresholds used by the agent-driven semantic audit in
# ``wiki-lint`` so the deterministic report and the semantic report agree.
PROVENANCE_AMBIGUOUS_WARN = 0.15
PROVENANCE_INFERRED_WARN = 0.40
PROVENANCE_SUM_TOLERANCE = 0.02

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_TOP_FIELD_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
_MARKER_RE = re.compile(r"\^\[(inferred|ambiguous)\]")


def _scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value.split(" #", 1)[0].strip()


def _parse_fraction(raw: str) -> float | None:
    try:
        value = float(_scalar(raw))
    except ValueError:
        return None
    if not 0.0 <= value <= 1.0:
        return None
    return value


def _parse_page(path: Path, vault: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatch = _FRONTMATTER_RE.match(text)
    frontmatter = frontmatch.group(1) if frontmatch else ""
    body = text[frontmatch.end():] if frontmatch else text

    values: dict[str, str] = {}
    provenance: dict[str, float | None] = {}
    block_sources = 0
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        field = _TOP_FIELD_RE.match(line)
        if field is None:
            index += 1
            continue
        key = field.group(1)
        raw = field.group(2).strip()
        values[key] = _scalar(raw)
        index += 1
        if key == "provenance":
            while index < len(lines) and lines[index].startswith((" ", "\t")):
                child = lines[index].strip()
                if ":" in child:
                    child_key, child_raw = child.split(":", 1)
                    provenance[child_key.strip()] = _parse_fraction(child_raw)
                index += 1
            continue
        if key == "sources":
            while index < len(lines) and lines[index].startswith((" ", "\t")):
                item = lines[index].strip()
                if item.startswith("-") and item[1:].strip():
                    block_sources += 1
                index += 1
            continue

    inline_sources = values.get("sources", "").strip().replace(" ", "")
    has_sources = bool(block_sources) or inline_sources not in {
        "",
        "[]",
        "null",
        "~",
        "{}",
    }
    markers = Counter(_MARKER_RE.findall(body))
    provenance_sum = (
        sum(value for value in provenance.values() if value is not None)
        if provenance
        else 0.0
    )
    invalid_provenance = bool(provenance) and (
        any(value is None for value in provenance.values())
        or provenance_sum > 1.0 + PROVENANCE_SUM_TOLERANCE
    )

    return {
        "path": path.relative_to(vault).as_posix(),
        "lifecycle": values.get("lifecycle", ""),
        "has_sources": has_sources,
        "has_provenance": bool(provenance),
        "provenance": provenance,
        "provenance_sum": provenance_sum,
        "invalid_provenance": invalid_provenance,
        "inferred_markers": markers.get("inferred", 0),
        "ambiguous_markers": markers.get("ambiguous", 0),
    }


def _mean_fractions(pages: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, list[float]] = defaultdict(list)
    for page in pages:
        for key, value in page["provenance"].items():
            if value is not None:
                totals[key].append(value)
    return {
        key: round(sum(values) / len(values), 3)
        for key, values in sorted(totals.items())
    }


def _signals(counts: dict[str, int]) -> dict[str, int]:
    return {key: int(value) for key, value in counts.items()}


def _dimension(
    status: str,
    *,
    signals: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "signals": signals or {},
        "notes": [note for note in notes or [] if note],
    }


def _structure_dimension(lint: dict[str, Any]) -> dict[str, Any]:
    findings = lint["findings"]
    counts = lint["stats"]["findings"]
    hard = counts["broken_links"] + counts["missing_frontmatter"]
    soft = counts["missing_summaries"] + counts["oversized_pages"]
    status = "fail" if hard else "warn" if soft else "pass"
    return _dimension(
        status,
        signals=_signals(
            {
                "broken_links": counts["broken_links"],
                "missing_frontmatter": counts["missing_frontmatter"],
                "missing_summaries": counts["missing_summaries"],
                "oversized_pages": counts["oversized_pages"],
            }
        ),
        notes=[
            f"{len(findings['broken_links'])} broken wikilink(s)"
            if findings["broken_links"]
            else "",
            f"{len(findings['oversized_pages'])} page(s) above the token ceiling"
            if findings["oversized_pages"]
            else "",
        ],
    )


def _provenance_drift_pages(pages: list[dict[str, Any]]) -> list[str]:
    return [
        page["path"]
        for page in pages
        if (
            page["provenance"].get("ambiguous") is not None
            and page["provenance"]["ambiguous"] > PROVENANCE_AMBIGUOUS_WARN
        )
        or (
            not page["has_sources"]
            and page["provenance"].get("inferred") is not None
            and page["provenance"]["inferred"] > PROVENANCE_INFERRED_WARN
        )
    ]


def _traceability_dimension(pages: list[dict[str, Any]]) -> dict[str, Any]:
    missing_sources = [page["path"] for page in pages if not page["has_sources"]]
    missing_provenance = [
        page["path"] for page in pages if not page["has_provenance"]
    ]
    invalid = [page["path"] for page in pages if page["invalid_provenance"]]
    drift = _provenance_drift_pages(pages)
    count = len(missing_sources) + len(missing_provenance) + len(invalid) + len(drift)
    return _dimension(
        "warn" if count else "pass",
        signals=_signals(
            {
                "pages_with_sources": sum(1 for page in pages if page["has_sources"]),
                "missing_sources": len(missing_sources),
                "missing_provenance": len(missing_provenance),
                "invalid_provenance": len(invalid),
                "provenance_drift": len(drift),
                "inferred_markers": sum(page["inferred_markers"] for page in pages),
                "ambiguous_markers": sum(page["ambiguous_markers"] for page in pages),
            }
        ),
        notes=[
            "pages without a source record cannot be audited"
            if missing_sources
            else "",
            "pages without a provenance block predate the current contract"
            if missing_provenance
            else "",
            f"{len(drift)} page(s) exceed the provenance drift threshold"
            if drift
            else "",
        ],
    )


def _consistency_dimension(lint: dict[str, Any]) -> dict[str, Any]:
    counts = lint["stats"]["findings"]
    total = (
        counts["duplicate_titles"]
        + counts["orphan_pages"]
        + counts["typed_relationship_issues"]
    )
    return _dimension(
        "warn" if total else "pass",
        signals=_signals(
            {
                "duplicate_title_groups": counts["duplicate_titles"],
                "orphan_pages": counts["orphan_pages"],
                "relationship_issues": counts["typed_relationship_issues"],
            }
        ),
        notes=[
            "semantic duplicate and contradiction detection is agent-driven; "
            "run the wiki-lint workflow for that pass"
        ],
    )


def _coverage_dimension(vault: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report = verify_completeness(vault)
    counts = report["stats"]["findings"]
    if report["stats"]["manifest_sources"] == 0:
        status = "not_measured"
        notes = ["no manifest entries yet; run an ingest to establish coverage"]
    elif report["status"] == "fail":
        status = "fail"
        notes = ["the manifest references pages that are missing or empty"]
    else:
        status = "pass"
        notes = []
    return (
        _dimension(
            status,
            signals=_signals(
                {
                    "manifest_sources": report["stats"]["manifest_sources"],
                    "sources_without_pages": counts["empty_pages"],
                    "phantom_pages": counts["phantom_pages"],
                }
            ),
            notes=notes,
        ),
        report,
    )


def _freshness_dimension(
    pages: list[dict[str, Any]], lint: dict[str, Any]
) -> dict[str, Any]:
    lifecycle = Counter(page["lifecycle"] or "(missing)" for page in pages)
    missing = lifecycle.get("(missing)", 0)
    stale_reviews = len(lint["findings"]["confidence_review_stale"])
    status = "warn" if missing or stale_reviews else "pass"
    notes = []
    if stale_reviews:
        notes.append(
            f"{stale_reviews} page(s) changed materially since their last review"
        )
    if lifecycle.get("disputed"):
        notes.append(
            f"{lifecycle['disputed']} disputed page(s) remain retrievable by design"
        )
    signals = {
        key: lifecycle.get(key, 0)
        for key in ("draft", "reviewed", "verified", "disputed", "archived")
    }
    for key in sorted(lifecycle):
        if key != "(missing)" and key not in signals:
            signals[key] = lifecycle[key]
    signals["missing_lifecycle"] = missing
    signals["stale_reviews"] = stale_reviews
    return _dimension(status, signals=_signals(signals), notes=notes)


def _trust_dimension(
    vault: Path,
    lint: dict[str, Any],
    *,
    strict_trust: bool,
    require_trust_ledger: bool,
) -> dict[str, Any]:
    findings = lint["findings"]
    counts = lint["stats"]["findings"]
    ledger_present = (vault / TRUST_LEDGER_RELATIVE_PATH).is_file()
    metadata_errors = counts["trust_metadata_errors"]
    missing_fields = counts["confidence_missing_fields"]
    ledger_errors = counts["confidence_ledger_errors"]
    mismatches = counts["confidence_mismatches"]
    stale = counts["confidence_review_stale"]
    unreviewed = counts["confidence_unreviewed"]

    if metadata_errors or ledger_errors or mismatches:
        status = "fail"
    elif strict_trust and (missing_fields or stale):
        status = "fail"
    elif require_trust_ledger and not ledger_present:
        status = "fail"
    elif ledger_present and (missing_fields or stale or unreviewed):
        status = "warn"
    elif missing_fields:
        status = "warn"
    elif not ledger_present:
        status = "not_measured"
    else:
        status = "pass"

    notes = []
    if not ledger_present:
        notes.append(
            "trust ledger is not configured; run `graph-wiki trust-record --all` "
            "after a human review to make confidence auditable"
        )
    if findings["trust_metadata_errors"]:
        notes.append("invalid lifecycle or confidence metadata must be fixed")
    if unreviewed:
        notes.append(f"{unreviewed} reviewable page(s) have no approved review")
    return _dimension(
        status,
        signals=_signals(
            {
                "ledger_configured": int(ledger_present),
                "metadata_errors": metadata_errors,
                "missing_fields": missing_fields,
                "ledger_errors": ledger_errors,
                "score_mismatches": mismatches,
                "stale_reviews": stale,
                "unreviewed": unreviewed,
            }
        ),
        notes=notes,
    )


def _retrieval_dimension() -> dict[str, Any]:
    return _dimension(
        "not_measured",
        notes=[
            "retrieval quality is evaluated by `graph-wiki pack eval`; "
            "answer-level grounding is not part of this report yet"
        ],
    )


def _overall_status(dimensions: dict[str, dict[str, Any]]) -> str:
    statuses = [dimension["status"] for dimension in dimensions.values()]
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def assess_quality(
    vault: Path,
    *,
    strict_trust: bool = False,
    require_trust_ledger: bool = False,
    allowed_lifecycles: Collection[str] | None = None,
    allowed_relationship_types: Collection[str] | None = None,
    required_trust_fields: Collection[str] | None = None,
    schema_source: str = "framework-defaults",
) -> dict[str, Any]:
    """Return one gate-ready quality report for *vault*."""
    vault = Path(vault)
    lint = lint_vault(
        vault,
        require_trust_ledger=False,
        strict_trust=False,
        allowed_relationship_types=allowed_relationship_types,
        allowed_lifecycles=allowed_lifecycles,
        required_trust_fields=required_trust_fields,
        schema_source=schema_source,
    )
    pages = [
        _parse_page(path, vault)
        for path in iter_content_pages(vault)
        if path.stem not in RESERVED_PAGE_STEMS
    ]

    coverage_dimension, coverage_report = _coverage_dimension(vault)
    dimensions = {
        "structure": _structure_dimension(lint),
        "traceability": _traceability_dimension(pages),
        "consistency": _consistency_dimension(lint),
        "coverage": coverage_dimension,
        "freshness": _freshness_dimension(pages, lint),
        "trust": _trust_dimension(
            vault,
            lint,
            strict_trust=strict_trust,
            require_trust_ledger=require_trust_ledger,
        ),
        "retrieval": _retrieval_dimension(),
    }
    status = _overall_status(dimensions)
    lifecycle = Counter(page["lifecycle"] or "(missing)" for page in pages)

    findings = dict(lint["findings"])
    findings["traceability"] = {
        "missing_sources": [
            page["path"] for page in pages if not page["has_sources"]
        ],
        "missing_provenance": [
            page["path"] for page in pages if not page["has_provenance"]
        ],
        "invalid_provenance": [
            page["path"] for page in pages if page["invalid_provenance"]
        ],
        "provenance_drift": _provenance_drift_pages(pages),
    }
    findings["coverage"] = coverage_report["findings"]

    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vault": str(vault),
        "schema": lint["schema"],
        "gate": {
            "strict_trust": bool(strict_trust),
            "require_trust_ledger": bool(require_trust_ledger),
            "failed_dimensions": [
                name
                for name, dimension in dimensions.items()
                if dimension["status"] == "fail"
            ],
            "warned_dimensions": [
                name
                for name, dimension in dimensions.items()
                if dimension["status"] == "warn"
            ],
        },
        "stats": {
            "pages": lint["stats"]["pages"],
            "content_pages": len(pages),
            "total_tokens": lint["stats"]["metrics"]["total_tokens"],
            "average_tokens": lint["stats"]["metrics"]["average_tokens"],
            "findings": lint["stats"]["findings"],
            "manifest_sources": coverage_report["stats"]["manifest_sources"],
            "trust": lint["stats"]["trust"],
        },
        "dimensions": dimensions,
        "metrics": {
            "lifecycle": {
                key: count
                for key, count in sorted(lifecycle.items())
                if key != "(missing)"
            },
            "missing_lifecycle": lifecycle.get("(missing)", 0),
            "provenance": {
                "pages_with_sources": sum(1 for page in pages if page["has_sources"]),
                "pages_with_provenance": sum(
                    1 for page in pages if page["has_provenance"]
                ),
                "mean_fractions": _mean_fractions(pages),
                "inferred_markers": sum(
                    page["inferred_markers"] for page in pages
                ),
                "ambiguous_markers": sum(
                    page["ambiguous_markers"] for page in pages
                ),
            },
            "duplicate_title_groups": lint["stats"]["metrics"][
                "duplicate_title_groups"
            ],
            "oversized_pages": lint["stats"]["metrics"]["oversized_pages"],
            "index_consistency": lint["stats"]["metrics"]["index_consistency"],
        },
        "findings": findings,
    }
