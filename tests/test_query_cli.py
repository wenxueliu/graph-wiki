"""Tests for the high-level query CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _page(vault: Path, name: str, *, title: str, summary: str, links: list[str] | None = None) -> None:
    path = vault / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"title: {title}",
        "category: concepts",
        "tags: [test]",
        "sources: [manual]",
        "created: 2026-07-01",
        "updated: 2026-07-01",
        f"summary: {summary}",
        "---",
        f"# {title}",
    ]
    for link in links or []:
        lines.append(f"[[{link}]]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "graph_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_query_cli_uses_configured_vault(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "transformer", title="Transformer Architecture", summary="Self-attention model.")
    _page(vault, "attention", title="Attention Mechanism", summary="Weighted lookup.", links=["transformer"])

    config_dir = home / ".graph-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(f'OBSIDIAN_VAULT_PATH="{vault}"\n', encoding="utf-8")

    proc = _run(home, "query", "transformer", "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert any(item["page"] == "transformer.md" for item in data["candidates"])


def test_query_cli_requires_vault_when_unconfigured(tmp_path: Path) -> None:
    home = tmp_path / "home"

    proc = _run(home, "query", "anything", "--json")

    assert proc.returncode == 1
    assert "vault not configured" in proc.stderr
