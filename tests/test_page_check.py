"""Tests for the pre-write page-check gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from graph_wiki.page_check import check_page

ROOT = Path(__file__).parents[1]


def _content(
    title: str = "Alpha",
    *,
    summary: str = "Alpha summary.",
    category: str = "concepts",
    aliases: list[str] | None = None,
    include_summary: bool = True,
    lifecycle: str = "reviewed",
) -> str:
    lines = [
        "---",
        f"title: {title}",
        f"category: {category}",
        "tags: [test]",
        "sources: [manual]",
        "created: 2026-07-01",
        "updated: 2026-07-01",
    ]
    if include_summary:
        lines.append(f"summary: {summary}")
    if aliases:
        lines.append("aliases:")
        lines.extend(f"  - {alias}" for alias in aliases)
    lines.extend(
        [
            "provenance:",
            "  extracted: 0.8",
            "  inferred: 0.2",
            "  ambiguous: 0.0",
            "base_confidence: 0.80",
            f"lifecycle: {lifecycle}",
            "lifecycle_changed: 2026-07-01",
            "tier: core",
            "---",
            f"# {title}",
        ]
    )
    return "\n".join(lines) + "\n"


def _page(
    vault: Path,
    relpath: str,
    title: str,
    *,
    summary: str = "Existing summary.",
    category: str = "concepts",
    aliases: list[str] | None = None,
) -> Path:
    path = vault / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _content(
            title,
            summary=summary,
            category=category,
            aliases=aliases,
        ),
        encoding="utf-8",
    )
    return path


def _run(vault: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HOME"] = str(vault.parent / "home")
    return subprocess.run(
        [sys.executable, "-m", "graph_wiki.cli", "page-check", str(vault), *args],
        capture_output=True,
        check=False,
        text=True,
        input=stdin,
        env=env,
    )


def test_page_check_passes_for_a_valid_new_page(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    report = check_page(
        vault,
        target="concepts/alpha.md",
        content=_content(),
    )

    assert report["status"] == "pass"
    assert report["mode"] == "create"
    assert report["validation"]["status"] == "pass"
    assert report["recommendation"] == "create"
    assert report["findings"]["duplicate_titles"] == []


def test_page_check_fails_on_incomplete_contract(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    report = check_page(
        vault,
        target="concepts/alpha.md",
        content=_content(include_summary=False),
    )

    assert report["status"] == "fail"
    assert "invalid_page" in report["hard_failures"]
    assert "summary" in report["validation"]["missing"]
    assert report["recommendation"] == "fix_contract"


def test_page_check_fails_when_create_target_exists(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha")

    report = check_page(
        vault,
        target="concepts/alpha.md",
        content=_content("Alpha Two"),
        mode="create",
    )

    assert report["status"] == "fail"
    assert report["findings"]["target_exists"] is True
    assert "target_exists" in report["hard_failures"]
    assert report["recommendation"] == "merge_or_update"


def test_page_check_allows_update_of_existing_target(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha")

    report = check_page(
        vault,
        target="concepts/alpha.md",
        content=_content("Alpha"),
        mode="update",
    )

    assert report["status"] == "pass"
    assert report["mode"] == "update"
    assert report["recommendation"] == "update"
    assert report["findings"]["duplicate_titles"] == []


def test_page_check_fails_when_update_target_is_missing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    report = check_page(
        vault,
        target="concepts/alpha.md",
        content=_content("Alpha"),
        mode="update",
    )

    assert report["status"] == "fail"
    assert "target_missing" in report["hard_failures"]
    assert report["recommendation"] == "create"


def test_page_check_warns_on_duplicate_title(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha")

    report = check_page(
        vault,
        target="entities/alpha-copy.md",
        content=_content("alpha"),
    )

    assert report["status"] == "warn"
    assert report["findings"]["duplicate_titles"] == [
        {"path": "concepts/alpha.md", "title": "Alpha"}
    ]
    assert report["recommendation"] == "merge_or_update"


def test_page_check_warns_when_planned_title_matches_an_alias(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(
        vault,
        "concepts/react-server-components.md",
        "React Server Components",
        aliases=["RSC"],
    )

    report = check_page(
        vault,
        target="concepts/rsc.md",
        content=_content("RSC"),
    )

    assert report["status"] == "warn"
    assert report["findings"]["alias_collisions"][0]["kind"] == "existing_alias"
    assert report["findings"]["alias_collisions"][0]["path"] == (
        "concepts/react-server-components.md"
    )


def test_page_check_reports_similar_pages_as_a_soft_signal(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/react-server-components.md", "React Server Components")

    report = check_page(
        vault,
        target="concepts/react-server-component.md",
        content=_content("React Server Component"),
    )

    assert report["status"] == "pass"
    assert report["recommendation"] == "inspect_similar"
    assert report["findings"]["similar_pages"][0]["path"] == (
        "concepts/react-server-components.md"
    )


def test_page_check_rejects_unsafe_or_system_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    traversal = check_page(
        vault,
        target="../escape.md",
        content=_content(),
    )
    system = check_page(
        vault,
        target="_staging/alpha.md",
        content=_content(),
    )

    assert traversal["status"] == "fail"
    assert traversal["findings"]["path_problem"]
    assert system["status"] == "fail"
    assert system["findings"]["path_problem"]


def test_page_check_cli_json_and_exit_codes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", "Alpha")

    passed = _run(
        vault,
        "--path",
        "concepts/beta.md",
        "--from-stdin",
        "--json",
        stdin=_content("Beta"),
    )
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["status"] == "pass"

    warned = _run(
        vault,
        "--path",
        "entities/alpha-copy.md",
        "--from-stdin",
        "--json",
        stdin=_content("Alpha"),
    )
    assert warned.returncode == 0
    assert json.loads(warned.stdout)["status"] == "warn"

    strict = _run(
        vault,
        "--path",
        "entities/alpha-copy.md",
        "--from-stdin",
        "--json",
        "--strict",
        stdin=_content("Alpha"),
    )
    assert strict.returncode == 1
