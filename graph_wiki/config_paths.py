"""Where the graph-wiki configuration directory lives.

The config directory holds ``config`` (the active vault), ``config.<name>``
(named vault profiles used by ``@name``), and ``WRITING.md``. It defaults to
``~/.graph-wiki`` but can be relocated so a project keeps its vault
configuration inside its own repository and never touches the home directory.

Resolution order:

1. ``GRAPH_WIKI_CONFIG_DIR`` in the process environment.
2. ``GRAPH_WIKI_CONFIG_DIR`` in the nearest ``.env`` found by walking up from
   the starting directory to ``$HOME``. A relative value resolves against that
   ``.env``'s directory, so ``GRAPH_WIKI_CONFIG_DIR=.graph-wiki`` keeps
   everything inside the project.
3. The caller's default, normally ``~/.graph-wiki``.

This module is dependency-free and imports nothing from the rest of the package,
so the standalone workflow scripts can reuse the same rules.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

CONFIG_DIR_ENV = "GRAPH_WIKI_CONFIG_DIR"


def read_env_value(path: Path, key: str) -> str:
    """Return a ``.env`` value with surrounding quotes stripped, or ``""``."""
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or not line.startswith(f"{key}="):
            continue
        return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def iter_parents(start: Path, home: Path) -> Iterator[Path]:
    """Yield ``start`` and each ancestor, stopping at ``home`` or the root."""
    current = start.resolve()
    home = home.resolve()
    while True:
        yield current
        if current == home or current.parent == current:
            return
        current = current.parent


def expand_config_dir(value: str, base: Path) -> Path:
    """Resolve a config-directory value, treating relative paths as ``base``-relative."""
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def resolve_config_dir(start: Path | None = None, *, default: Path) -> Path:
    """Resolve the config directory for a working directory.

    ``default`` is used when neither the environment nor any ``.env`` relocates
    it. Callers pass their own default so tests can substitute one.
    """
    override = os.environ.get(CONFIG_DIR_ENV, "").strip()
    if override:
        return expand_config_dir(override, Path.cwd())

    origin = Path(start) if start is not None else Path.cwd()
    home = Path.home()
    for directory in iter_parents(origin, home):
        env_file = directory / ".env"
        if not env_file.is_file():
            continue
        value = read_env_value(env_file, CONFIG_DIR_ENV)
        if value:
            return expand_config_dir(value, env_file.parent)
    return default


def config_file(name: str | None = None, *, default: Path, start: Path | None = None) -> Path:
    """Path to ``config`` or ``config.<name>``."""
    directory = resolve_config_dir(start, default=default)
    return directory / (f"config.{name}" if name else "config")


def writing_profile_file(*, default: Path, start: Path | None = None) -> Path:
    """Path to the global writing profile inside the resolved config directory."""
    return resolve_config_dir(start, default=default) / "WRITING.md"
