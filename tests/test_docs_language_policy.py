"""Docs language policy: English and Simplified Chinese only.

The project ships documentation in exactly two languages. Every page under `docs/`
has an English `<name>.md` and a Simplified Chinese `<name>.zh-CN.md` mirror, and
the root README pair is `README.md` / `README_ZH.md`. Traditional Chinese and any
other locale are out of scope, so a stray `zh-TW` file is a regression rather than
a cosmetic wart.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# Locale tokens in a mirror-style file name (`cli.zh-TW.md` → `zh-TW`).
UNSUPPORTED_LOCALES = ("zh-TW", "zh-Hant", "zh_Hant", "ja", "ko", "fr", "de", "es", "pt", "ru")


def locale_tokens(name: str) -> list[str]:
    """Dot-separated tokens after the base name, e.g. `cli.zh-CN.md` → ['zh-CN']."""
    stem = name[: -len(".md")] if name.endswith(".md") else name
    return stem.split(".")[1:]


def english_pages() -> list[Path]:
    return sorted(p for p in DOCS.glob("*.md") if not p.name.endswith(".zh-CN.md"))


def test_no_traditional_chinese_or_unsupported_locale_files() -> None:
    leftovers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in DOCS.glob("*.md")
        if any(
            token == locale or token.startswith("zh-TW") or token.startswith("zh-Hant")
            for token in locale_tokens(path.name)
            for locale in UNSUPPORTED_LOCALES
        )
    )
    assert leftovers == []
    assert not (ROOT / "README_TW.md").exists()


def test_every_english_page_has_a_simplified_chinese_mirror() -> None:
    missing = [
        page.name
        for page in english_pages()
        if not (DOCS / f"{page.stem}.zh-CN.md").exists()
    ]
    assert missing == []


def test_no_orphan_simplified_chinese_mirrors() -> None:
    orphans = sorted(
        page.name
        for page in DOCS.glob("*.zh-CN.md")
        if not (DOCS / f"{page.name[: -len('.zh-CN.md')]}.md").exists()
    )
    assert orphans == []


def test_english_pages_declare_the_language_switcher() -> None:
    missing = [
        page.name
        for page in english_pages()
        if f"[简体中文]({page.stem}.zh-CN.md)" not in page.read_text(encoding="utf-8")
    ]
    assert missing == []


def test_simplified_chinese_mirrors_link_back_to_english() -> None:
    missing = [
        page.name
        for page in sorted(DOCS.glob("*.zh-CN.md"))
        if f"[English]({page.name[: -len('.zh-CN.md')]}.md)" not in page.read_text(
            encoding="utf-8"
        )
    ]
    assert missing == []


def test_root_readme_pair_is_the_two_supported_languages() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "README_ZH.md").read_text(encoding="utf-8")

    assert "README_ZH.md" in english
    assert "README.md" in chinese
    assert "README_TW.md" not in english
    assert "README_TW.md" not in chinese
    # Same heading depth sequence keeps the two READMEs one documentation surface.
    levels = re.compile(r"^(#{1,3}) .+$", re.MULTILINE)
    assert [len(m) for m in levels.findall(english)] == [
        len(m) for m in levels.findall(chinese)
    ]
