"""Shared vault page set for the viewer and the operations inventory.

Both surfaces need the same definition of "a page a human can open": Markdown
files inside the active Pack's content roots, minus operational bookkeeping
files.  Keeping that filter in one place prevents the viewer and the
operations report from disagreeing about what counts as a page.
"""

from __future__ import annotations

from pathlib import Path

from graph_wiki.knowledge_pack import iter_content_pages

SYSTEM_FILES = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "_insights.md",
        "hot.md",
        "index.md",
        "log.md",
    }
)
ROOT_ONLY_FILES = frozenset({"README.md"})
# Obsidian's own configuration, plugin bundles, and trash are never knowledge
# pages.  They matter especially for uninitialized vaults, where the content
# roots are discovered by walking the whole tree.
ALWAYS_SKIP_DIRS = frozenset({".obsidian", ".trash", ".git"})


def page_files(vault: Path) -> list[Path]:
    """Return page files in deterministic order, excluding bookkeeping."""
    vault = Path(vault)
    files: list[Path] = []
    for path in iter_content_pages(vault):
        relative = path.relative_to(vault)
        if any(part in ALWAYS_SKIP_DIRS for part in relative.parts):
            continue
        if relative.name in SYSTEM_FILES:
            continue
        if relative.parent == Path(".") and relative.name in ROOT_ONLY_FILES:
            continue
        files.append(path)
    files.sort(key=lambda item: item.relative_to(vault).as_posix())
    return files
