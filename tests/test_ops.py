"""Tests for the operations event store, inventory, and report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from graph_wiki import ops


TZ = timezone(timedelta(hours=8))


def _page(
    vault: Path,
    name: str,
    *,
    title: str = "Page",
    body: str = "Body.",
    updated: str = "2025-01-01",
    lifecycle: str = "reviewed",
    confidence: float = 0.7,
    summary: str = "Short summary.",
) -> Path:
    path = vault / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"title: {title}",
                "category: concepts",
                "tags: [test]",
                f"summary: {summary}",
                f"lifecycle: {lifecycle}",
                f"base_confidence: {confidence}",
                "created: 2020-01-01",
                f"updated: {updated}",
                "sources:",
                "  - source_id: S1",
                "    revision: r1",
                "---",
                "# " + title,
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_scan_tracks_baseline_updates_renames_and_deletes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    page = _page(vault, "concepts/retry")
    ops_dir = tmp_path / "ops"
    now = datetime(2026, 11, 26, 12, 0, tzinfo=TZ)

    baseline = ops.scan(vault, ops_dir=ops_dir, now=now)
    assert baseline["baseline"] is True
    assert baseline["pages"] == 1
    inventory = ops.load_inventory(ops.ops_paths(vault, ops_dir=ops_dir))
    assert inventory is not None
    assert inventory["pages"]["concepts/retry"]["version"] == 1

    page.write_text(page.read_text().replace("Body.", "Body with jitter."), encoding="utf-8")
    summary = ops.scan(vault, ops_dir=ops_dir, now=now + timedelta(minutes=1))
    assert summary["updated"] == 1
    assert summary["history_events"] == 1
    history = [json.loads(line) for line in (ops_dir / "history.jsonl").read_text().splitlines()]
    assert history[-1]["event"] == "updated"
    assert history[-1]["version"] == 2
    assert history[-1]["changes"] == ["body"]
    inventory = ops.load_inventory(ops.ops_paths(vault, ops_dir=ops_dir))
    assert inventory["pages"]["concepts/retry"]["version"] == 2
    assert "updated_not_bumped" in ops.build_report(
        vault, days=30, ops_dir=ops_dir, now=now + timedelta(days=1)
    )["metadata_health"]

    page.write_text(page.read_text().replace("updated: 2025-01-01", "updated: 2025-01-02"), encoding="utf-8")
    summary = ops.scan(vault, ops_dir=ops_dir, now=now + timedelta(minutes=2))
    assert summary["metadata_only"] == 1
    inventory = ops.load_inventory(ops.ops_paths(vault, ops_dir=ops_dir))
    assert inventory["pages"]["concepts/retry"]["version"] == 2

    renamed = vault / "concepts/retry-v2.md"
    renamed.write_text(page.read_text(), encoding="utf-8")
    page.unlink()
    summary = ops.scan(vault, ops_dir=ops_dir, now=now + timedelta(minutes=3))
    assert summary["renamed"] == 1
    assert summary["deleted"] == 0
    inventory = ops.load_inventory(ops.ops_paths(vault, ops_dir=ops_dir))
    assert inventory["pages"]["concepts/retry-v2"]["version"] == 2

    renamed.unlink()
    summary = ops.scan(vault, ops_dir=ops_dir, now=now + timedelta(minutes=4))
    assert summary["deleted"] == 1
    assert "concepts/retry-v2" not in ops.load_inventory(ops.ops_paths(vault, ops_dir=ops_dir))["pages"]


def test_report_counts_views_dedupe_sources_and_retrievals(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/retry", title="Retry")
    _page(vault, "concepts/cache", title="Cache")
    _page(vault, "concepts/silent", title="Silent")
    ops_dir = tmp_path / "ops"
    now = datetime(2026, 11, 26, 12, 0, tzinfo=TZ)
    ops.scan(vault, ops_dir=ops_dir, now=now)

    ops.record_event(vault, event="view", page="concepts/retry", source="viewer", client="c1", ts="2026-11-26T09:00:00+08:00", ops_dir=ops_dir)
    ops.record_event(vault, event="view", page="concepts/retry", source="viewer", client="c1", ts="2026-11-26T09:10:00+08:00", ops_dir=ops_dir)
    ops.record_event(vault, event="view", page="concepts/retry", source="viewer", client="c1", ts="2026-11-26T09:40:00+08:00", ops_dir=ops_dir)
    ops.record_event(vault, event="view", page="concepts/cache", source="obsidian", client="obs-1", ts="2026-11-26T10:00:00+08:00", ops_dir=ops_dir)
    ops.record_event(vault, event="retrieval", page="concepts/cache", source="query", client="agent", ts="2026-11-26T11:00:00+08:00", ops_dir=ops_dir)
    ops.record_event(vault, event="retrieval", page="concepts/cache", source="context-pack", client="agent", ts="2026-11-26T11:05:00+08:00", ops_dir=ops_dir)

    report = ops.build_report(vault, days=30, top=10, ops_dir=ops_dir, now=now)
    assert report["views"]["total"] == 3
    assert report["views"]["raw"] == 4
    assert report["views"]["by_source"] == {"viewer": 2, "obsidian": 1}
    assert report["views"]["top"][0]["page"] == "concepts/retry"
    assert report["views"]["top"][0]["views"] == 2
    assert report["views"]["zero_view_pages"] == 1
    assert report["views"]["never_viewed_pages"] == 1
    assert report["retrievals"]["total"] == 2
    assert report["retrievals"]["by_source"] == {"query": 1, "context-pack": 1}

    rendered = ops.render_markdown(report)
    assert "Retry" in rendered
    assert "Most viewed" in rendered


def test_report_includes_review_overdue_and_aging(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/old", title="Old", updated="2020-01-01")
    meta = vault / "_meta"
    meta.mkdir()
    (meta / "trust-ledger.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pages": {
                    "concepts/old.md": {
                        "reviewed_at": "2020-01-01T00:00:00+00:00",
                        "reviewed_confidence": 0.7,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    ops_dir = tmp_path / "ops"
    now = datetime(2026, 11, 26, 12, 0, tzinfo=TZ)
    ops.scan(vault, ops_dir=ops_dir, now=now)
    report = ops.build_report(vault, days=30, aging_days=365, ops_dir=ops_dir, now=now)
    assert report["expiry"]["overdue_pages"] == 1
    assert report["expiry"]["review_overdue"][0]["page"] == "concepts/old"
    assert report["expiry"]["aging_pages"] == 1
    assert report["expiry"]["aging"][0]["age_days"] > 365


def test_event_validation_and_state_location(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/retry")
    with pytest.raises(ops.OpsError):
        ops.normalize_event({"event": "open", "page": "concepts/retry", "source": "viewer"})
    with pytest.raises(ops.OpsError):
        ops.normalize_event({"event": "view", "page": "../escape", "source": "viewer"})
    with pytest.raises(ops.OpsError):
        ops.ops_paths(vault, ops_dir=vault / "ops")

    with pytest.raises(ops.OpsError):
        ops.save_report(vault / "report.json", {"views": {}}, vault=vault)


def test_scan_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/retry")
    ops_dir = tmp_path / "ops"
    first = ops.scan(vault, ops_dir=ops_dir)
    second = ops.scan(vault, ops_dir=ops_dir)
    assert second["history_events"] == 0
    assert second["pages"] == first["pages"]


def test_install_obsidian_plugin(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    result = ops.install_obsidian_plugin(vault, port=8765, ops_dir=tmp_path / "ops")
    plugin = Path(result["plugin_dir"])
    assert (plugin / "manifest.json").is_file()
    assert (plugin / "main.js").is_file()
    settings = json.loads((plugin / "data.json").read_text())
    assert settings["port"] == 8765
    assert settings["token"]
    assert settings["clientId"].startswith("obsidian-")
    again = ops.install_obsidian_plugin(vault, port=8765, ops_dir=tmp_path / "ops")
    assert again["client_id"] == settings["clientId"]
    forced = ops.install_obsidian_plugin(
        vault, port=8765, ops_dir=tmp_path / "ops", force=True
    )
    assert forced["client_id"] != settings["clientId"]
