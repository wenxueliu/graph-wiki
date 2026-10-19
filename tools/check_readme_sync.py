"""Report README translation drift.

For each translation (README_ZH.md), lists commits that changed
README.md after the last commit that touched that translation, plus the
combined English diff that still needs to be translated and backfilled.
Translations not yet tracked in HEAD are skipped, so adding a new one does
not flag the entire history. Advisory only — exits 1 on drift so callers can
detect it, but CI never uses it to block a merge.
"""
from __future__ import annotations

import subprocess


ENGLISH = "README.md"
TRANSLATIONS = ("README_ZH.md",)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def is_tracked(path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{path}", "--"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def check_translation(translation: str) -> bool:
    """Report drift for one translation. Returns True when drift was found."""
    # ponytail: a translation-only commit marks everything before it as synced;
    # per-commit pairing if that ever misleads
    last = git("log", "-1", "--format=%H", "--", translation).strip()
    log_range = f"{last}..HEAD" if last else "HEAD"
    pending = git("log", "--format=%h %s", log_range, "--", ENGLISH).strip()

    if not pending:
        print(f"{translation} is up to date with {ENGLISH}.")
        return False

    print(f"Commits that changed {ENGLISH} without a later {translation} update:")
    print(pending)
    print()
    print(f"English changes not yet reflected in {translation}:")
    if last:
        print(git("diff", log_range, "--", ENGLISH))
    else:
        print(f"{translation} has no history — the entire {ENGLISH} is untranslated.")
    print(f"Translate the changes above and backfill them into {translation}.")
    return True


def main() -> int:
    drifted = False
    for translation in TRANSLATIONS:
        if not is_tracked(translation):
            print(f"{translation} is not tracked yet — skipping.")
            continue
        if check_translation(translation):
            drifted = True
            print()
    if not drifted:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
