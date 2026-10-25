from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_version_lookup_uses_the_pyproject_distribution_name() -> None:
    """`--version` must resolve the installed distribution, not a stale name."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^name\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    assert match is not None
    distribution = match.group(1)

    init = (ROOT / "graph_wiki" / "__init__.py").read_text(encoding="utf-8")
    assert f'version("{distribution}")' in init
