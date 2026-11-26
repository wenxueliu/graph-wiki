"""CLI tests for operations commands and retrieval instrumentation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from graph_wiki.cli import build_parser
from graph_wiki.ops import ops_paths


def _page(vault: Path, name: str, *, title: str, summary: str) -> None:
    path = vault / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"title: {title}",
                "category: concepts",
                "tags: [test]",
                "sources: [manual]",
                "created: 2025-01-01",
                "updated: 2025-01-01",
                f"summary: {summary}",
                "lifecycle: reviewed",
                "base_confidence: 0.6",
                "---",
                f"# {title}",
                f"{summary} retry cache consistency.",
            ]
        ),
        encoding="utf-8",
    )


def _run(home: Path, *args: str, env_ops: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if env_ops is not None:
        env["GRAPH_WIKI_OPS"] = env_ops
    else:
        env.pop("GRAPH_WIKI_OPS", None)
    return subprocess.run(
        [sys.executable, "-m", "graph_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _events(home: Path, vault: Path) -> list[dict]:
    paths = ops_paths(vault, base=home / ".graph-wiki" / "state")
    events: list[dict] = []
    if not paths.events.is_dir():
        return events
    for path in sorted(paths.events.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def test_cli_parser_exposes_ops_and_serve_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["ops", "report", "/tmp/vault", "--days", "7", "--json"])
    assert args.func.__name__ == "cmd_ops"
    assert args.ops_cmd == "report"
    assert args.days == 7
    assert args.json is True

    args = parser.parse_args(["serve", "--ops", "--no-ops", "--ops-dir", "/tmp/ops"])
    assert args.ops is True
    assert args.no_ops is True
    assert args.ops_dir == "/tmp/ops"


def test_ops_record_and_report_roundtrip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/retry", title="Retry", summary="Retry policy")
    home = tmp_path / "home"
    home.mkdir()
    ops_dir = tmp_path / "state" / "ops"

    result = _run(
        home,
        "ops",
        "scan",
        str(vault),
        "--ops-dir",
        str(ops_dir),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pages"] == 1

    result = _run(
        home,
        "ops",
        "record",
        str(vault),
        "--page",
        "concepts/retry",
        "--source",
        "viewer",
        "--client",
        "cli-1",
        "--ops-dir",
        str(ops_dir),
        "--json",
    )
    assert result.returncode == 0, result.stderr

    result = _run(
        home,
        "ops",
        "report",
        str(vault),
        "--ops-dir",
        str(ops_dir),
        "--no-scan",
        "--json",
        "--pretty",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["views"]["total"] == 1
    assert report["views"]["top"][0]["page"] == "concepts/retry"

    destination = tmp_path / "report.json"
    result = _run(
        home,
        "ops",
        "report",
        str(vault),
        "--ops-dir",
        str(ops_dir),
        "--no-scan",
        "--save",
        str(destination),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert destination.is_file()


def test_ops_ingest_strict_rejects_invalid_lines(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/retry", title="Retry", summary="Retry policy")
    home = tmp_path / "home"
    home.mkdir()
    ops_dir = tmp_path / "state" / "ops"
    source = tmp_path / "events.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "view",
                        "page": "concepts/retry",
                        "source": "portal",
                        "client": "u-1",
                    }
                ),
                "not-json",
                json.dumps({"event": "open", "page": "concepts/retry", "source": "portal"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = _run(
        home,
        "ops",
        "ingest",
        str(vault),
        "--file",
        str(source),
        "--ops-dir",
        str(ops_dir),
        "--strict",
        "--json",
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["accepted"] == 1
    assert payload["rejected"] == 1
    assert len(payload["parse_errors"]) == 1


def test_query_records_retrieval_only_when_enabled(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/retry", title="Retry", summary="Retry policy")
    _page(vault, "concepts/cache", title="Cache", summary="Cache consistency")
    home = tmp_path / "home"
    home.mkdir()

    result = _run(home, "query", "retry cache", "--vault", str(vault), "--json")
    assert result.returncode == 0, result.stderr
    assert _events(home, vault) == []

    result = _run(home, "query", "retry cache", "--vault", str(vault), "--json", env_ops="1")
    assert result.returncode == 0, result.stderr
    events = _events(home, vault)
    assert events
    assert all(event["event"] == "retrieval" for event in events)
    assert all(event["source"] == "query" for event in events)
    assert all(event["client"] == "agent" for event in events)
    assert {event["page"] for event in events} <= {"concepts/retry", "concepts/cache"}

    # A second process with recording disabled must not add anything.
    before = len(_events(home, vault))
    result = _run(home, "query", "retry cache", "--vault", str(vault), "--json", env_ops="0")
    assert result.returncode == 0, result.stderr
    assert len(_events(home, vault)) == before


def test_context_pack_records_included_pages(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _page(vault, "concepts/retry", title="Retry", summary="Retry policy")
    _page(vault, "concepts/cache", title="Cache", summary="Cache consistency")
    home = tmp_path / "home"
    home.mkdir()

    result = _run(home, "context-pack", "retry", "--vault", str(vault), "--json", env_ops="1")
    assert result.returncode == 0, result.stderr
    pack = json.loads(result.stdout)
    events = _events(home, vault)
    assert events
    assert all(event["source"] == "context-pack" for event in events)
    assert {event["page"] for event in events} == {
        entry["path"][:-3] if entry["path"].endswith(".md") else entry["path"]
        for entry in pack["pages"]
    }
