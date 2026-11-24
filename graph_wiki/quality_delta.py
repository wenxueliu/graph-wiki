"""Compare two quality reports and summarize what changed.

``quality --baseline <snapshot> --save <snapshot>`` uses this module to turn a
daily check into a delta: which findings appeared, which were fixed, and whether
the overall status moved. Snapshots live outside the vault (usually the
vault-scoped state directory), so this comparison never mutates knowledge.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

_STATUS_RANK = {"pass": 0, "warn": 1, "fail": 2}
_FINDING_CATEGORIES = (
    "broken_links",
    "missing_frontmatter",
    "duplicate_titles",
    "missing_summaries",
    "oversized_pages",
    "orphan_pages",
    "typed_relationship_issues",
    "confidence_missing_fields",
    "trust_metadata_errors",
    "confidence_review_stale",
    "confidence_unreviewed",
    "confidence_mismatches",
    "confidence_ledger_errors",
    "review_overdue",
    "review_due_soon",
    "contradictions",
    "disputed_pages",
    "duplicate_candidates",
)
_NESTED_FINDINGS = {
    "traceability": (
        "missing_sources",
        "missing_provenance",
        "invalid_provenance",
        "provenance_drift",
    ),
    "coverage": ("empty_pages", "phantom_pages"),
}


def load_quality_report(path: str | Path) -> dict[str, Any] | None:
    """Read a saved quality report, or return ``None`` when unusable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        return None
    return data


def save_quality_report(path: str | Path, report: dict[str, Any]) -> None:
    """Atomically save a report without its transient ``delta`` block."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {key: value for key, value in report.items() if key != "delta"}
    payload = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
    try:
        temporary.replace(destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _item_key(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, (list, tuple)):
        return "|".join(str(part) for part in item)
    if isinstance(item, dict):
        if "source" in item and "target" in item:
            return f"{item['source']}->{item['target']}"
        if "left" in item and "right" in item:
            return f"{item['left']}<->{item['right']}"
        if "page" in item and "target" in item:
            return f"{item['page']}->{item['target']}"
        if "page" in item:
            return str(item["page"])
        if "path" in item:
            return str(item["path"])
        if "title" in item:
            return str(item["title"])
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    return str(item)


def _finding_sets(report: dict[str, Any]) -> dict[str, set[str]]:
    findings = report.get("findings")
    if not isinstance(findings, dict):
        return {}
    result: dict[str, set[str]] = {}
    for category in _FINDING_CATEGORIES:
        items = findings.get(category)
        if isinstance(items, list):
            result[category] = {_item_key(item) for item in items}
    for parent, categories in _NESTED_FINDINGS.items():
        nested = findings.get(parent)
        if not isinstance(nested, dict):
            continue
        for category in categories:
            items = nested.get(category)
            if isinstance(items, list):
                result[category] = {_item_key(item) for item in items}
    return result


def _counts(report: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    stats = report.get("stats")
    if isinstance(stats, dict):
        for key in (
            "pages",
            "content_pages",
            "total_tokens",
            "average_tokens",
            "manifest_sources",
        ):
            value = stats.get(key)
            if isinstance(value, int):
                result[key] = value
        findings = stats.get("findings")
        if isinstance(findings, dict):
            for key, value in findings.items():
                if isinstance(value, int):
                    result[f"findings.{key}"] = value
    metrics = report.get("metrics")
    if isinstance(metrics, dict):
        for key in (
            "duplicate_title_groups",
            "oversized_pages",
            "contradictions",
            "disputed_pages",
            "duplicate_candidates",
            "missing_lifecycle",
        ):
            value = metrics.get(key)
            if isinstance(value, int):
                result[f"metrics.{key}"] = value
        review = metrics.get("review")
        if isinstance(review, dict):
            for key, value in review.items():
                if isinstance(value, int):
                    result[f"review.{key}"] = value
    return result


def _dimension_statuses(report: dict[str, Any]) -> dict[str, str]:
    dimensions = report.get("dimensions")
    if not isinstance(dimensions, dict):
        return {}
    return {
        name: str(dimension.get("status"))
        for name, dimension in dimensions.items()
        if isinstance(dimension, dict)
    }


def compare_quality(
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> dict[str, Any]:
    """Return the delta between a baseline report and the current report."""
    if before is None:
        return {
            "status": "first_run",
            "baseline_generated_at": None,
            "current_generated_at": after.get("generated_at"),
            "totals": {"new": 0, "resolved": 0},
        }

    before_status = str(before.get("status", "pass"))
    after_status = str(after.get("status", "pass"))
    before_dimensions = _dimension_statuses(before)
    after_dimensions = _dimension_statuses(after)
    dimension_changes = {
        name: {"before": before_dimensions.get(name), "after": after_dimensions.get(name)}
        for name in sorted(set(before_dimensions) | set(after_dimensions))
        if before_dimensions.get(name) != after_dimensions.get(name)
    }

    before_sets = _finding_sets(before)
    after_sets = _finding_sets(after)
    new_findings: dict[str, list[str]] = {}
    resolved_findings: dict[str, list[str]] = {}
    for category in sorted(set(before_sets) | set(after_sets)):
        added = after_sets.get(category, set()) - before_sets.get(category, set())
        removed = before_sets.get(category, set()) - after_sets.get(category, set())
        if added:
            new_findings[category] = sorted(added)
        if removed:
            resolved_findings[category] = sorted(removed)

    before_counts = _counts(before)
    after_counts = _counts(after)
    counts = {
        key: {
            "before": before_counts.get(key, 0),
            "after": after_counts.get(key, 0),
            "delta": after_counts.get(key, 0) - before_counts.get(key, 0),
        }
        for key in sorted(set(before_counts) | set(after_counts))
    }

    total_new = sum(len(items) for items in new_findings.values())
    total_resolved = sum(len(items) for items in resolved_findings.values())
    before_rank = _STATUS_RANK.get(before_status, 1)
    after_rank = _STATUS_RANK.get(after_status, 1)
    if after_rank > before_rank:
        status = "regressed"
    elif after_rank < before_rank:
        status = "improved"
    elif total_new and not total_resolved:
        status = "regressed"
    elif total_resolved and not total_new:
        status = "improved"
    elif total_new > total_resolved:
        status = "regressed"
    elif total_resolved > total_new:
        status = "improved"
    else:
        status = "stable"

    return {
        "status": status,
        "baseline_generated_at": before.get("generated_at"),
        "current_generated_at": after.get("generated_at"),
        "status_change": {"before": before_status, "after": after_status},
        "dimension_changes": dimension_changes,
        "counts": counts,
        "new_findings": new_findings,
        "resolved_findings": resolved_findings,
        "totals": {"new": total_new, "resolved": total_resolved},
    }
