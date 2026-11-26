"""Packaging and manifest guards for the bundled Obsidian collector."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "extensions" / "obsidian-ops"


def test_plugin_files_exist() -> None:
    assert (PLUGIN / "manifest.json").is_file()
    assert (PLUGIN / "main.js").is_file()
    manifest = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "graph-wiki-ops"
    assert manifest["isDesktopOnly"] is True


def test_plugin_sends_only_expected_fields() -> None:
    source = (PLUGIN / "main.js").read_text(encoding="utf-8")
    assert 'event: "view"' in source
    assert 'source: "obsidian"' in source
    assert "X-Graph-Wiki-Ops-Token" in source
    assert "onLayoutReady" in source


@unittest.skipIf(tomllib is None, "tomllib requires Python 3.11+")
def test_plugin_is_force_included_in_builds() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert (
        wheel["force-include"]["extensions/obsidian-ops"]
        == "graph_wiki/_data/extensions/obsidian-ops"
    )
    sdist = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert (
        sdist["force-include"]["extensions/obsidian-ops"]
        == "extensions/obsidian-ops"
    )
