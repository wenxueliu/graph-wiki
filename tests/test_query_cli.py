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


def _build_pack(home: Path, vault: Path, store: Path) -> None:
    proc = _run(
        home,
        "pack",
        "build",
        "--vault",
        str(vault),
        "--store",
        str(store),
        "--channel",
        "release",
        "--index",
        "sqlite",
    )
    assert proc.returncode == 0, proc.stderr


def test_query_cli_pinned_mode_reads_pack_index(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    store = tmp_path / "packs"
    _page(vault, "transformer", title="Transformer Architecture", summary="Self-attention model.")
    _page(vault, "attention", title="Attention Mechanism", summary="Weighted lookup.", links=["transformer"])
    _build_pack(home, vault, store)

    proc = _run(
        home,
        "query",
        "attention",
        "--mode",
        "pinned",
        "--vault",
        str(vault),
        "--store",
        str(store),
        "--channel",
        "release",
        "--json",
    )

    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["mode"] == "pinned"
    assert data["version"] == 1
    assert data["pack_id"].startswith("sha256:")
    assert data["index_id"].startswith("sha256:")
    assert any(item["path"] == "attention.md" for item in data["candidates"])


def test_query_cli_pinned_mode_follows_config_switch(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    store = tmp_path / "packs"
    _page(vault, "attention", title="Attention Mechanism", summary="Weighted lookup.")
    _build_pack(home, vault, store)

    config_dir = home / ".graph-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(
        f'OBSIDIAN_VAULT_PATH="{vault}"\n'
        "WIKI_RETRIEVAL_MODE=pinned\n"
        "WIKI_PACK_CHANNEL=release\n",
        encoding="utf-8",
    )

    proc = _run(home, "query", "attention", "--store", str(store), "--json")

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["mode"] == "pinned"


def test_query_cli_pinned_mode_fails_closed_without_pack(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "attention", title="Attention Mechanism", summary="Weighted lookup.")

    config_dir = home / ".graph-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(
        f'OBSIDIAN_VAULT_PATH="{vault}"\nWIKI_RETRIEVAL_MODE=pinned\n',
        encoding="utf-8",
    )

    proc = _run(home, "query", "attention", "--store", str(tmp_path / "empty-store"), "--json")

    assert proc.returncode == 1
    assert "no packs found" in proc.stderr


def test_query_cli_live_mode_overrides_pinned_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    store = tmp_path / "packs"
    _page(vault, "attention", title="Attention Mechanism", summary="Weighted lookup.")
    _build_pack(home, vault, store)

    config_dir = home / ".graph-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(
        f'OBSIDIAN_VAULT_PATH="{vault}"\nWIKI_RETRIEVAL_MODE=pinned\n',
        encoding="utf-8",
    )

    proc = _run(home, "query", "attention", "--mode", "live", "--json")

    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "answer_type" in data
    assert data.get("mode") != "pinned"
