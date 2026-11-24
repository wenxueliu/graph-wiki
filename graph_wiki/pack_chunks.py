"""Shared, deterministic chunking and tokenization for pack indexes.

Both index engines consume the same chunks.  Zvec can analyze raw text with
its native Jieba tokenizer; the SQLite FTS5 backend needs pre-segmented text,
so :func:`segment_text` provides a stdlib-only word + CJK bigram stream.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from graph_wiki.pack import PackError
from graph_wiki.relationships import split_frontmatter


CHUNK_POLICY = "headings-v1"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TOKEN_RE = re.compile(
    r"[a-z0-9]+(?:[._+#-][a-z0-9]+)*"
    r"|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]+"
)
_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in",
     "is", "it", "of", "on", "or", "that", "the", "to", "was", "what", "when",
     "where", "which", "who", "why", "with"}
)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    page_id: str
    path: str
    ordinal: int
    heading_path: str
    line_start: int
    line_end: int
    text: str
    search_text: str
    title: str
    summary: str
    tags: tuple[str, ...]
    sha256: str
    lifecycle: str
    tier: str
    updated: str
    verified_at: str
    stale_after: str
    expires_at: str


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _is_cjk(character: str) -> bool:
    code = ord(character)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def segment_text(text: str, *, mode: str = "bigram", for_query: bool = False) -> list[str]:
    """Tokenize Latin words and CJK runs into a deterministic token stream.

    ``mode="bigram"`` emits CJK unigrams and bigrams so a two-character query
    can match word-level phrases. ``mode="simple"`` is the lightweight
    baseline: Latin words plus one token per CJK character, no bigrams.
    """
    if mode not in {"bigram", "simple"}:
        raise ValueError(f"unknown tokenizer mode: {mode}")
    normalised = unicodedata.normalize("NFKC", text).casefold()
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(normalised):
        token = match.group(0)
        if _is_cjk(token[0]):
            characters = list(token)
            if mode == "simple":
                tokens.extend(characters)
                continue
            if for_query:
                if len(characters) == 1:
                    tokens.append(characters[0])
                else:
                    tokens.extend("".join(characters[i:i + 2]) for i in range(len(characters) - 1))
            else:
                tokens.extend(characters)
                tokens.extend("".join(characters[i:i + 2]) for i in range(len(characters) - 1))
            continue
        if token in _STOPWORDS:
            continue
        tokens.append(token)
        parts = [part for part in re.split(r"[._+#-]+", token) if part]
        if len(parts) > 1:
            tokens.extend(part for part in parts if part not in _STOPWORDS)
    if for_query:
        seen: set[str] = set()
        deduped: list[str] = []
        for token in tokens:
            if token not in seen:
                seen.add(token)
                deduped.append(token)
        return deduped
    return tokens


def _chunk_body(title: str, summary: str, tags: tuple[str, ...], body: str) -> list[tuple[str, int, int, str]]:
    """Return ``(heading_path, line_start, line_end, text)`` tuples."""
    lines = body.splitlines()
    headings = []
    fence = ""
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not fence:
                fence = marker
            elif marker == fence:
                fence = ""
            continue
        if fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))

    chunks: list[tuple[str, int, int, str]] = []
    if not headings:
        text = body.strip()
        if text:
            chunks.append(("", 1, max(len(lines), 1), text))
        return chunks

    first_heading = headings[0][0]
    preamble = "\n".join(lines[:first_heading]).strip()
    if preamble:
        chunks.append(("", 1, max(first_heading, 1), preamble))

    stack: list[tuple[int, str]] = []
    for position, (index, level, heading) in enumerate(headings):
        end = headings[position + 1][0] - 1 if position + 1 < len(headings) else len(lines) - 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        heading_path = " > ".join(item[1] for item in stack)
        text = "\n".join(lines[index:end + 1]).strip()
        if text:
            chunks.append((heading_path, index + 1, end + 1, text))
    return chunks


def iter_chunks(pack_dir: Path) -> Iterator[Chunk]:
    """Yield deterministic chunk documents for one content pack."""
    pack_dir = Path(pack_dir)
    inventory_path = pack_dir / "inventory.jsonl"
    if not inventory_path.is_file():
        raise PackError(f"pack inventory is missing: {inventory_path}")
    body_offset = 0
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        body_path = pack_dir / "bodies" / f"{entry['sha256'].removeprefix('sha256:')}.md"
        if not body_path.is_file():
            raise PackError(f"missing body for {entry.get('path')}")
        text = _normalise(body_path.read_text(encoding="utf-8"))
        _front, body = split_frontmatter(text)
        body_offset = text[: len(text) - len(body)].count("\n")

        title = str(entry.get("title", ""))
        summary = str(entry.get("summary", ""))
        tags = tuple(str(tag) for tag in entry.get("tags", []))
        page_id = str(entry["path"])
        common = {
            "page_id": page_id,
            "path": page_id,
            "title": title,
            "summary": summary,
            "tags": tags,
            "sha256": entry["sha256"],
            "lifecycle": str(entry.get("lifecycle", "")),
            "tier": str(entry.get("tier", "")),
            "updated": str(entry.get("updated", "")),
            "verified_at": str(entry.get("verified_at", "")),
            "stale_after": str(entry.get("stale_after", "")),
            "expires_at": str(entry.get("expires_at", "")),
        }
        ordinal = 0
        synthetic = " ".join(part for part in (title, summary, " ".join(tags)) if part).strip()
        if synthetic:
            yield Chunk(
                chunk_id=f"{page_id}#0000",
                ordinal=0,
                heading_path="summary",
                line_start=0,
                line_end=0,
                text=summary or title,
                search_text=synthetic,
                **common,
            )
            ordinal = 1

        for heading_path, start, end, chunk_text in _chunk_body(title, summary, tags, body):
            yield Chunk(
                chunk_id=f"{page_id}#{ordinal:04d}",
                ordinal=ordinal,
                heading_path=heading_path,
                line_start=start + body_offset,
                line_end=end + body_offset,
                text=chunk_text,
                search_text=f"{heading_path}\n{chunk_text}".strip(),
                **common,
            )
            ordinal += 1
