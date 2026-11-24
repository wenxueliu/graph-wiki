"""Pre-write page gate: contract validation plus canonical duplicate detection.

Agents compose pages in memory or a temporary file. Before that content becomes
a live canonical page, ``page-check`` answers two deterministic questions:

1. Does the planned page satisfy the page contract (frontmatter, provenance)?
2. Does the vault already hold a page with the same identity (title, alias, or
   slug), or a strongly similar one that should be merged instead?

The gate never writes to the vault. It fails on contract violations and target
mode mismatches, and warns on duplicate identities so an agent must merge,
update, or consciously justify a separate page.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from graph_wiki.knowledge_pack import (
    KNOWLEDGE_PACK_MARKER,
    active_knowledge_pack,
    iter_content_pages,
)
from graph_wiki.validate import validate_text

RESERVED_PAGE_STEMS = frozenset({"index", "log", "hot", "_insights"})
SIMILAR_TITLE_JACCARD = 0.60
SIMILAR_SUMMARY_JACCARD = 0.75
SIMILAR_LIMIT = 5

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_TOP_FIELD_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
_INLINE_LIST_RE = re.compile(r"^\[(.*)\]$")
_BLOCK_SCALAR_RE = re.compile(r"^[>|][+-]?\d*$")
_NORMALISE_RE = re.compile(r"[\W_]+", re.UNICODE)
_LATIN_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value.split(" #", 1)[0].strip()


def _parse_fields(frontmatter: str) -> dict[str, list[str]]:
    records: dict[str, list[str]] = {}
    current: str | None = None
    for line in frontmatter.splitlines():
        field = _TOP_FIELD_RE.match(line)
        if field is not None:
            current = field.group(1)
            records[current] = [field.group(2).strip()]
            continue
        if current is not None and line.startswith((" ", "\t")):
            records[current].append(line.strip())
            continue
        if line.strip():
            current = None
    return records


def _field_scalar(records: dict[str, list[str]], key: str) -> str:
    values = records.get(key)
    if not values:
        return ""
    raw = values[0]
    if raw and not _BLOCK_SCALAR_RE.match(raw):
        return _scalar(raw)
    folded = [
        line.lstrip("- ").strip()
        for line in values[1:]
        if line.strip() and not line.strip().startswith("#")
    ]
    return " ".join(folded).strip()


def _field_list(records: dict[str, list[str]], key: str) -> list[str]:
    values = records.get(key)
    if not values:
        return []
    raw = values[0]
    inline = _INLINE_LIST_RE.match(raw)
    if inline is not None:
        items = [
            _scalar(item)
            for item in inline.group(1).split(",")
        ]
        return [item for item in items if item]
    items = []
    for line in [raw, *values[1:]]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-"):
            item = _scalar(stripped[1:])
            if item:
                items.append(item)
        elif not _INLINE_LIST_RE.match(stripped) and values[0] == raw and stripped == raw:
            item = _scalar(stripped)
            if item:
                items.append(item)
    return items


def _normalise(text: str) -> str:
    return _NORMALISE_RE.sub("", unicodedata.normalize("NFKC", text).casefold())


def _slug(text: str) -> str:
    return _NORMALISE_RE.sub("-", unicodedata.normalize("NFKC", text).casefold()).strip("-")


def _tokens(text: str) -> set[str]:
    if not text.strip():
        return set()
    normalised = unicodedata.normalize("NFKC", text).casefold()
    latin = _LATIN_RE.findall(normalised)
    cjk = _CJK_RE.findall(normalised)
    bigrams = [cjk[index] + cjk[index + 1] for index in range(len(cjk) - 1)]
    return set(latin + cjk + bigrams)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union)


def _identity(text: str, *, fallback_title: str) -> dict[str, Any]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {"title": fallback_title, "aliases": [], "tags": [], "summary": "", "category": ""}
    records = _parse_fields(match.group(1))
    title = _field_scalar(records, "title") or fallback_title
    aliases = _field_list(records, "aliases") + _field_list(records, "alias")
    return {
        "title": title,
        "aliases": list(dict.fromkeys(aliases)),
        "tags": _field_list(records, "tags"),
        "summary": _field_scalar(records, "summary"),
        "category": _field_scalar(records, "category"),
    }


def _path_problem(vault: Path, target: str, pack: Any) -> str | None:
    candidate = Path(target)
    if not target.strip():
        return "target path is empty"
    if candidate.is_absolute() or ".." in candidate.parts:
        return "target must be a safe vault-relative path"
    if candidate.suffix.lower() != ".md":
        return "target must end with .md"
    relative = candidate.as_posix().removeprefix("./")
    if candidate.stem.lower() in RESERVED_PAGE_STEMS:
        return f"target is a reserved special file: {candidate.name}"
    if any(
        part in pack.skip_dirs or part in pack.system_dirs
        for part in candidate.parts[:-1]
    ):
        return "target is inside a system or skipped area"
    if (vault / KNOWLEDGE_PACK_MARKER).is_file():
        roots = pack.content_roots
        if not any(
            relative == root or relative.startswith(root + "/")
            for root in roots
        ):
            return "target is outside the active Pack's content roots"
    vault_root = vault.resolve()
    resolved = (vault / relative).resolve()
    if resolved != vault_root and vault_root not in resolved.parents:
        return "target resolves outside the vault"
    return None


def _similar_pages(
    planned: dict[str, Any],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    planned_title = _normalise(planned["title"])
    planned_title_tokens = _tokens(planned["title"])
    planned_summary_tokens = _tokens(planned["summary"])
    candidates: list[dict[str, Any]] = []
    for page in existing:
        title = _normalise(page["title"])
        if not title or title == planned_title:
            continue
        title_score = _jaccard(planned_title_tokens, _tokens(page["title"]))
        summary_score = _jaccard(planned_summary_tokens, _tokens(page["summary"]))
        reason = ""
        score = 0.0
        if (
            len(planned_title) >= 4
            and len(title) >= 4
            and (planned_title in title or title in planned_title)
        ):
            reason = "title_substring"
            score = 0.80
        elif title_score >= SIMILAR_TITLE_JACCARD:
            reason = "title_tokens"
            score = title_score
        elif (
            summary_score >= SIMILAR_SUMMARY_JACCARD
            and planned["category"] == page["category"]
        ):
            reason = "summary_tokens"
            score = summary_score
        if reason:
            candidates.append(
                {
                    "path": page["path"],
                    "title": page["title"],
                    "score": round(score, 3),
                    "reason": reason,
                }
            )
    candidates.sort(key=lambda item: (-item["score"], item["path"]))
    return candidates[:SIMILAR_LIMIT]


def check_page(
    vault: Path,
    *,
    target: str,
    content: str,
    mode: str | None = None,
) -> dict[str, Any]:
    """Check whether *content* may be written to *target* in *vault*."""
    vault = Path(vault)
    pack = active_knowledge_pack(vault)
    relative = Path(target).as_posix().removeprefix("./")
    problem = _path_problem(vault, target, pack)

    target_path = vault / relative
    target_exists = target_path.is_file()
    if mode not in {"create", "update"}:
        mode = "update" if target_exists else "create"

    validation = validate_text(content, path=relative)
    planned = _identity(content, fallback_title=Path(relative).stem)

    existing: list[dict[str, Any]] = []
    if problem is None:
        target_resolved = target_path.resolve()
        for path in iter_content_pages(vault):
            if path.stem in RESERVED_PAGE_STEMS:
                continue
            if path.resolve() == target_resolved:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            identity = _identity(text, fallback_title=path.stem)
            identity["path"] = path.relative_to(vault).as_posix()
            existing.append(identity)

    planned_title = _normalise(planned["title"])
    planned_aliases = [_normalise(alias) for alias in planned["aliases"] if _normalise(alias)]
    duplicate_titles = [
        {"path": page["path"], "title": page["title"]}
        for page in existing
        if planned_title and _normalise(page["title"]) == planned_title
    ]
    alias_collisions: list[dict[str, str]] = []
    for page in existing:
        page_title = _normalise(page["title"])
        page_aliases = {_normalise(alias) for alias in page["aliases"] if _normalise(alias)}
        for alias in planned_aliases:
            if alias == page_title or alias in page_aliases:
                alias_collisions.append(
                    {
                        "path": page["path"],
                        "title": page["title"],
                        "matched": alias,
                        "kind": "planned_alias",
                    }
                )
                break
        if planned_title and planned_title in page_aliases:
            alias_collisions.append(
                {
                    "path": page["path"],
                    "title": page["title"],
                    "matched": planned["title"],
                    "kind": "existing_alias",
                }
            )
    slug_collisions = [
        {"path": page["path"], "title": page["title"]}
        for page in existing
        if _slug(Path(page["path"]).stem) == _slug(Path(relative).stem)
    ]
    similar = _similar_pages(planned, existing) if problem is None else []

    hard_failures: list[str] = []
    if problem is not None:
        hard_failures.append("invalid_target")
    if not validation.get("ok", False):
        hard_failures.append("invalid_page")
    if mode == "create" and target_exists:
        hard_failures.append("target_exists")
    if mode == "update" and not target_exists:
        hard_failures.append("target_missing")

    warnings = bool(duplicate_titles or alias_collisions)
    status = "fail" if hard_failures else "warn" if warnings else "pass"
    if hard_failures:
        if "invalid_page" in hard_failures or "invalid_target" in hard_failures:
            recommendation = "fix_contract"
        elif "target_missing" in hard_failures:
            recommendation = "create"
        else:
            recommendation = "merge_or_update"
    elif warnings:
        recommendation = "merge_or_update"
    elif similar:
        recommendation = "inspect_similar"
    else:
        recommendation = "update" if mode == "update" else "create"

    return {
        "status": status,
        "vault": str(vault),
        "target": relative,
        "mode": mode,
        "page": planned,
        "validation": {
            "status": "pass" if validation.get("ok", False) else "fail",
            "missing": validation.get("missing", []),
            "warnings": validation.get("warnings", []),
            "error": validation.get("error", ""),
        },
        "findings": {
            "path_problem": problem,
            "target_exists": target_exists,
            "duplicate_titles": duplicate_titles,
            "alias_collisions": alias_collisions,
            "slug_collisions": slug_collisions,
            "similar_pages": similar,
        },
        "hard_failures": hard_failures,
        "recommendation": recommendation,
    }
