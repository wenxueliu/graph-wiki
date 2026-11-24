"""Tests for the deterministic knowledge-quality report."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from graph_wiki.quality import assess_quality
from graph_wiki.quality_delta import compare_quality
from graph_wiki.trust import build_trust_ledger, write_trust_ledger

ROOT = Path(__file__).parents[1]


def _page(
    vault: Path,
    relpath: str,
    *,
    title: str | None = None,
    sources: str = "[manual]",
    provenance: bool = True,
    lifecycle: str = "reviewed",
    links: list[str] | None = None,
    extra: str = "",
) -> Path:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"title: {title or path.stem}",
        "category: concepts",
        "tags: [test]",
        f"sources: {sources}",
        "created: 2026-07-01",
        "updated: 2026-07-01",
        "summary: Short summary.",
    ]
    if provenance:
        lines.extend(
            [
                "provenance:",
                "  extracted: 0.8",
                "  inferred: 0.2",
                "  ambiguous: 0.0",
            ]
        )
    lines.extend(
        [
            "base_confidence: 0.80",
            f"lifecycle: {lifecycle}",
            "lifecycle_changed: 2026-07-01",
            *extra.splitlines(),
            "---",
            f"# {title or path.stem}",
        ]
    )
    for link in links or []:
        lines.append(f"[[{link}]]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _clean_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", links=["beta"])
    _page(vault, "concepts/beta.md", lifecycle="verified", links=["alpha"])
    return vault


def _run(vault: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HOME"] = str(vault.parent / "home")
    return subprocess.run(
        [sys.executable, "-m", "graph_wiki.cli", "quality", str(vault), *args],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )


def test_quality_passes_clean_vault_and_marks_unmeasured_dimensions(
    tmp_path: Path,
) -> None:
    report = assess_quality(_clean_vault(tmp_path))

    assert report["status"] == "pass"
    assert report["dimensions"]["structure"]["status"] == "pass"
    assert report["dimensions"]["traceability"]["status"] == "pass"
    assert report["dimensions"]["consistency"]["status"] == "pass"
    assert report["dimensions"]["freshness"]["status"] == "pass"
    assert report["dimensions"]["trust"]["status"] == "not_measured"
    assert report["dimensions"]["coverage"]["status"] == "not_measured"
    assert report["dimensions"]["retrieval"]["status"] == "not_measured"


def test_quality_fails_on_broken_links(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", links=["ghost"])
    _page(vault, "concepts/beta.md", links=["alpha"])

    report = assess_quality(vault)

    assert report["status"] == "fail"
    assert report["dimensions"]["structure"]["status"] == "fail"
    assert report["gate"]["failed_dimensions"] == ["structure"]
    assert report["findings"]["broken_links"] == [
        {"page": "concepts/alpha.md", "target": "ghost"}
    ]


def test_quality_warns_on_missing_sources_and_provenance(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", sources="[]", provenance=False, links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])

    report = assess_quality(vault)

    assert report["status"] == "warn"
    traceability = report["dimensions"]["traceability"]
    assert traceability["status"] == "warn"
    assert traceability["signals"]["missing_sources"] == 1
    assert traceability["signals"]["missing_provenance"] == 1
    assert report["findings"]["traceability"]["missing_sources"] == [
        "concepts/alpha.md"
    ]


def test_quality_detects_provenance_drift(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    path = _page(vault, "concepts/alpha.md", links=["beta"])
    text = path.read_text(encoding="utf-8").replace("ambiguous: 0.0", "ambiguous: 0.4")
    path.write_text(text, encoding="utf-8")
    _page(vault, "concepts/beta.md", links=["alpha"])

    report = assess_quality(vault)

    assert report["dimensions"]["traceability"]["status"] == "warn"
    assert report["dimensions"]["traceability"]["signals"]["provenance_drift"] == 1
    assert report["findings"]["traceability"]["provenance_drift"] == [
        "concepts/alpha.md"
    ]


def test_quality_fails_on_phantom_manifest_pages(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)
    (vault / ".manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "path": "/tmp/source.md",
                        "content_hash": "sha256:abc",
                        "pages_produced": ["concepts/missing.md"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = assess_quality(vault)

    assert report["status"] == "fail"
    assert report["dimensions"]["coverage"]["status"] == "fail"
    assert report["stats"]["manifest_sources"] == 1


def test_quality_fails_on_invalid_lifecycle_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", lifecycle="active", links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])

    report = assess_quality(vault)

    assert report["status"] == "fail"
    assert report["dimensions"]["trust"]["status"] == "fail"
    assert report["dimensions"]["trust"]["signals"]["metadata_errors"] == 1


def test_quality_passes_when_trust_ledger_is_complete(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)
    ledger = build_trust_ledger(vault, reviewed_at="2026-07-12T17:38:39+07:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)

    report = assess_quality(vault)

    assert report["status"] == "pass"
    assert report["dimensions"]["trust"]["status"] == "pass"
    assert report["dimensions"]["trust"]["signals"]["ledger_configured"] == 1


def test_quality_requires_trust_ledger_when_requested(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)

    report = assess_quality(vault, require_trust_ledger=True)

    assert report["status"] == "fail"
    assert report["dimensions"]["trust"]["status"] == "fail"


def test_quality_cli_json_and_exit_codes(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)

    passed = _run(vault, "--json")
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["status"] == "pass"

    _page(vault, "concepts/alpha.md", sources="[]", provenance=False, links=["beta"])
    warned = _run(vault, "--json")
    assert warned.returncode == 0
    assert json.loads(warned.stdout)["status"] == "warn"

    strict = _run(vault, "--strict", "--json")
    assert strict.returncode == 1
    assert json.loads(strict.stdout)["status"] == "warn"


def test_quality_reports_owner_extended_lifecycle(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", lifecycle="active", links=["beta"])
    _page(vault, "concepts/beta.md", links=["alpha"])

    report = assess_quality(
        vault,
        allowed_lifecycles={
            "draft",
            "reviewed",
            "verified",
            "disputed",
            "archived",
            "active",
        },
    )

    assert report["status"] == "pass"
    assert report["dimensions"]["freshness"]["signals"]["active"] == 1
    assert report["metrics"]["lifecycle"]["active"] == 1


def test_quality_cli_requires_trust_ledger_for_release_gate(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)

    result = _run(vault, "--require-trust-ledger", "--json")

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "fail"
    assert report["dimensions"]["trust"]["status"] == "fail"


def test_quality_review_sla_marks_overdue_reviews(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)
    ledger = build_trust_ledger(vault, reviewed_at="2025-01-02T00:00:00+00:00")
    write_trust_ledger(vault / "_meta" / "trust-ledger.json", ledger, vault=vault)

    report = assess_quality(
        vault,
        now=datetime(2026, 11, 24, tzinfo=timezone.utc),
    )

    assert report["dimensions"]["freshness"]["status"] == "warn"
    assert report["dimensions"]["freshness"]["signals"]["review_overdue"] == 2
    assert len(report["findings"]["review_overdue"]) == 2
    assert report["findings"]["review_overdue"][0]["days_overdue"] > 0
    assert report["metrics"]["review"]["overdue"] == 2


def test_quality_registers_contradictions_and_duplicate_candidates(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    _page(
        vault,
        "concepts/alpha.md",
        extra='relationships:\n  - type: contradicts\n    target: "[[beta]]"',
    )
    _page(vault, "concepts/beta.md", extra="aliases:\n  - Alpha")

    report = assess_quality(vault)

    assert report["findings"]["contradictions"] == [
        {"source": "concepts/alpha.md", "target": "beta", "kind": "relationship"}
    ]
    assert report["findings"]["duplicate_candidates"][0]["reason"] == (
        "alias_matches_title"
    )
    assert report["dimensions"]["consistency"]["signals"]["contradictions"] == 1
    assert report["dimensions"]["consistency"]["signals"]["duplicate_candidates"] == 1


def test_compare_quality_reports_new_and_resolved_findings(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)
    before = assess_quality(vault)

    _page(vault, "concepts/beta.md", title="Beta", links=["ghost"])
    after = assess_quality(vault)
    regressed = compare_quality(before, after)

    assert regressed["status"] == "regressed"
    assert "broken_links" in regressed["new_findings"]
    assert regressed["totals"]["new"] >= 1

    _page(vault, "concepts/beta.md", title="Beta", links=["alpha"])
    recovered = assess_quality(vault)
    improved = compare_quality(after, recovered)

    assert improved["status"] == "improved"
    assert "broken_links" in improved["resolved_findings"]


def test_quality_cli_baseline_and_save(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)
    snapshot = tmp_path / "state" / "quality.json"

    first = _run(vault, "--json", "--save", str(snapshot))
    assert first.returncode == 0
    assert snapshot.is_file()

    _page(vault, "concepts/beta.md", title="Beta", links=["ghost"])
    second = _run(
        vault,
        "--json",
        "--baseline",
        str(snapshot),
        "--save",
        str(snapshot),
    )

    assert second.returncode == 1
    report = json.loads(second.stdout)
    assert report["delta"]["status"] == "regressed"
    assert "broken_links" in report["delta"]["new_findings"]


def test_quality_cli_rejects_snapshot_inside_vault(tmp_path: Path) -> None:
    vault = _clean_vault(tmp_path)

    result = _run(vault, "--json", "--save", str(vault / "quality.json"))

    assert result.returncode == 1
    assert not (vault / "quality.json").exists()
