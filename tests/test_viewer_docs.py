"""The viewer docs and CLI must agree on the page/retrieval boundary."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_viewer_docs_cover_the_command_and_retrieval_boundary() -> None:
    for name in ("viewer.md", "viewer.zh-CN.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "graph-wiki serve" in text
        assert "zvec" in text
        assert "/api/graph" in text
        assert "/api/page" in text
        assert "max_bytes" in text
        assert "ETag" in text


def test_cli_docs_list_serve() -> None:
    for name in ("cli.md", "cli.zh-CN.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "graph-wiki serve" in text


def test_installation_and_configuration_link_the_viewer() -> None:
    for name in (
        "installation.md",
        "installation.zh-CN.md",
        "configuration.md",
        "configuration.zh-CN.md",
    ):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "graph-wiki serve" in text, name
