"""Rebuildable retrieval indexes over a content pack.

Two engines share the same chunk stream:

* ``sqlite`` — stdlib FTS5 with pre-segmented text (word + CJK bigram).
* ``zvec``   — optional native BM25 + Jieba FTS, opened read-only.

Indexes are derived artifacts.  They never contribute to ``pack_id`` and can
always be rebuilt from ``manifest.json`` plus the body CAS.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from graph_wiki.pack import PackError, load_manifest
from graph_wiki.pack_chunks import CHUNK_POLICY, Chunk, iter_chunks, segment_text


SQLITE_ENGINE = "sqlite"
SQLITE_SIMPLE_ENGINE = "sqlite-simple"
ZVEC_ENGINE = "zvec"
ENGINES = (SQLITE_ENGINE, SQLITE_SIMPLE_ENGINE, ZVEC_ENGINE)

_SQLITE_FTS5: bool | None = None
_ZVEC_READY = False
_ZVEC_MODULE: Any = None
_ZVEC_COLLECTIONS: dict[str, Any] = {}


class PackIndexError(PackError):
    """An index could not be built or queried."""


def sqlite_fts5_available() -> bool:
    global _SQLITE_FTS5
    if _SQLITE_FTS5 is None:
        try:
            connection = sqlite3.connect(":memory:")
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
            connection.close()
            _SQLITE_FTS5 = True
        except sqlite3.Error:
            _SQLITE_FTS5 = False
    return _SQLITE_FTS5


def zvec_available() -> bool:
    if importlib.util.find_spec("zvec") is None:
        return False
    return True


def engine_status() -> dict[str, dict[str, Any]]:
    return {
        SQLITE_ENGINE: {
            "available": sqlite_fts5_available(),
            "reason": None if sqlite_fts5_available() else "sqlite3 was built without FTS5",
            "python": "stdlib",
        },
        SQLITE_SIMPLE_ENGINE: {
            "available": sqlite_fts5_available(),
            "reason": None if sqlite_fts5_available() else "sqlite3 was built without FTS5",
            "python": "stdlib",
        },
        ZVEC_ENGINE: {
            "available": zvec_available(),
            "reason": None if zvec_available() else "install graph-wiki-skills[pack-zvec]",
            "python": "optional",
        },
    }


def engine_tokenizer(engine: str) -> str:
    """Return the tokenizer recorded for an engine."""
    return {
        SQLITE_ENGINE: "bigram",
        SQLITE_SIMPLE_ENGINE: "simple",
        ZVEC_ENGINE: "jieba",
    }.get(engine.lower(), "")


def _load_zvec() -> Any:
    global _ZVEC_MODULE, _ZVEC_READY
    if _ZVEC_MODULE is None:
        try:
            _ZVEC_MODULE = importlib.import_module("zvec")
        except ImportError as exc:
            raise PackIndexError(
                "zvec is not installed; install graph-wiki-skills[pack-zvec]"
            ) from exc
    if not _ZVEC_READY:
        try:
            _ZVEC_MODULE.init()
        except RuntimeError:
            pass
        _ZVEC_READY = True
    return _ZVEC_MODULE


def _engine_version(engine: str) -> str:
    if engine in (SQLITE_ENGINE, SQLITE_SIMPLE_ENGINE):
        return sqlite3.sqlite_version
    return str(_load_zvec().__version__)


def _index_dir(pack_dir: Path, engine: str) -> Path:
    return Path(pack_dir) / "indexes" / engine


def _load_meta(index_dir: Path) -> dict[str, Any]:
    path = Path(index_dir) / "index.json"
    if not path.is_file():
        raise PackIndexError(f"index is missing: {index_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def available_indexes(pack_dir: Path) -> list[str]:
    base = Path(pack_dir) / "indexes"
    if not base.is_dir():
        return []
    return [
        child.name
        for child in sorted(base.iterdir())
        if child.is_dir() and (child / "index.json").is_file()
    ]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _index_id(content_pack_id: str, engine: str, engine_version: str, config: dict[str, Any]) -> str:
    import hashlib

    payload = {
        "content_pack_id": content_pack_id,
        "engine": engine,
        "engine_version": engine_version,
        "config": config,
        "chunk_policy": CHUNK_POLICY,
    }
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def build_index(pack_dir: Path, engine: str, *, force: bool = False) -> dict[str, Any]:
    """Build one engine index sidecar; idempotent when content is unchanged."""
    pack_dir = Path(pack_dir)
    engine = engine.lower()
    if engine not in ENGINES:
        raise PackIndexError(f"unknown index engine: {engine}")
    manifest = load_manifest(pack_dir)
    if engine in (SQLITE_ENGINE, SQLITE_SIMPLE_ENGINE) and not sqlite_fts5_available():
        raise PackIndexError("sqlite3 was built without FTS5")
    if engine == ZVEC_ENGINE and not zvec_available():
        raise PackIndexError("zvec is not installed; install graph-wiki-skills[pack-zvec]")

    expected_tokenizer = engine_tokenizer(engine)
    final = _index_dir(pack_dir, engine)
    if final.exists() and not force:
        try:
            existing = _load_meta(final)
        except (OSError, ValueError):
            existing = {}
        if (
            existing.get("content_pack_id") == manifest["pack_id"]
            and existing.get("engine_version") == _engine_version(engine)
            and existing.get("chunk_policy") == CHUNK_POLICY
            and existing.get("config", {}).get("tokenizer") == expected_tokenizer
        ):
            return existing
        raise PackIndexError(f"index is stale; rerun with --force: {final}")

    chunks = list(iter_chunks(pack_dir))
    if not chunks:
        raise PackIndexError("pack contains no indexable chunks")
    config = {"tokenizer": expected_tokenizer, "operator": "AND"}
    engine_version = _engine_version(engine)
    meta = {
        "index_format": 1,
        "engine": engine,
        "engine_version": engine_version,
        "content_pack_id": manifest["pack_id"],
        "index_id": _index_id(manifest["pack_id"], engine, engine_version, config),
        "chunk_policy": CHUNK_POLICY,
        "config": config,
        "counts": {"chunks": len(chunks), "pages": len({chunk.page_id for chunk in chunks})},
        "built_at": manifest.get("created_at"),
    }

    indexes = pack_dir / "indexes"
    indexes.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{engine}-", dir=indexes))
    try:
        if engine in (SQLITE_ENGINE, SQLITE_SIMPLE_ENGINE):
            _build_sqlite(chunks, temporary, tokenizer=expected_tokenizer)
        else:
            _build_zvec(chunks, temporary)
        (temporary / "index.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if final.exists():
            shutil.rmtree(final)
        os.replace(temporary, final)
        _ZVEC_COLLECTIONS.pop(str(final.resolve()), None)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return meta


# ── SQLite FTS5 ─────────────────────────────────────────────────────────────


def _build_sqlite(chunks: list[Chunk], directory: Path, *, tokenizer: str) -> None:
    connection = sqlite3.connect(directory / "index.sqlite")
    try:
        connection.executescript(
            """
            CREATE TABLE pages (
                page_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                lifecycle TEXT,
                tier TEXT,
                updated TEXT,
                verified_at TEXT,
                stale_after TEXT,
                expires_at TEXT,
                sha256 TEXT,
                tags_json TEXT
            );
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                page_id TEXT NOT NULL,
                ordinal INTEGER,
                heading_path TEXT,
                line_start INTEGER,
                line_end INTEGER,
                text TEXT,
                search_text TEXT
            );
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                chunk_id UNINDEXED,
                fts_text,
                tokenize='unicode61'
            );
            """
        )
        pages: dict[str, Chunk] = {}
        for chunk in chunks:
            pages.setdefault(chunk.page_id, chunk)
        connection.executemany(
            "INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    chunk.page_id, chunk.path, chunk.title, chunk.summary,
                    chunk.lifecycle, chunk.tier, chunk.updated, chunk.verified_at,
                    chunk.stale_after, chunk.expires_at, chunk.sha256,
                    json.dumps(list(chunk.tags), ensure_ascii=False),
                )
                for chunk in pages.values()
            ],
        )
        connection.executemany(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    chunk.chunk_id, chunk.page_id, chunk.ordinal, chunk.heading_path,
                    chunk.line_start, chunk.line_end, chunk.text, chunk.search_text,
                )
                for chunk in chunks
            ],
        )
        connection.executemany(
            "INSERT INTO chunks_fts VALUES (?,?)",
            [
                (chunk.chunk_id, " ".join(segment_text(chunk.search_text, mode=tokenizer)))
                for chunk in chunks
            ],
        )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()


def _sqlite_search(
    index_dir: Path,
    query: str,
    *,
    topk: int,
    operator: str,
    include_archived: bool,
    tokenizer: str,
) -> list[dict[str, Any]]:
    terms = segment_text(query, mode=tokenizer, for_query=True)
    if not terms:
        return []
    match = (" AND " if operator.upper() != "OR" else " OR ").join(
        '"' + term.replace('"', '""') + '"' for term in terms
    )
    clauses = ["chunks_fts MATCH ?"]
    parameters: list[Any] = [match]
    if not include_archived:
        clauses.append("p.lifecycle != 'archived'")
    sql = f"""
        SELECT c.chunk_id, c.page_id, c.ordinal, c.heading_path,
               c.line_start, c.line_end, c.text,
               p.path, p.title, p.sha256, p.lifecycle, p.stale_after, p.expires_at,
               bm25(chunks_fts) AS rank
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        JOIN pages p ON p.page_id = c.page_id
        WHERE {' AND '.join(clauses)}
        ORDER BY rank ASC, c.chunk_id ASC
        LIMIT ?
    """
    parameters.append(max(topk * 5, topk))
    database = quote((index_dir / "index.sqlite").resolve().as_posix(), safe="/:")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    results = []
    for row in rows:
        results.append(
            {
                "chunk_id": row["chunk_id"],
                "page_id": row["page_id"],
                "path": row["path"],
                "title": row["title"],
                "heading": row["heading_path"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "text": row["text"],
                "sha256": row["sha256"],
                "lifecycle": row["lifecycle"],
                "stale_after": row["stale_after"],
                "expires_at": row["expires_at"],
                "score": -float(row["rank"]),
            }
        )
    return results


# ── Zvec ────────────────────────────────────────────────────────────────────


def _zvec_schema(zvec: Any) -> Any:
    return zvec.CollectionSchema(
        name="wiki_pack",
        fields=[
            zvec.FieldSchema("path", zvec.DataType.STRING, index_param=zvec.InvertIndexParam()),
            zvec.FieldSchema("page_id", zvec.DataType.STRING),
            zvec.FieldSchema("title", zvec.DataType.STRING),
            zvec.FieldSchema("summary", zvec.DataType.STRING),
            zvec.FieldSchema("heading", zvec.DataType.STRING),
            zvec.FieldSchema("line_start", zvec.DataType.INT64),
            zvec.FieldSchema("line_end", zvec.DataType.INT64),
            zvec.FieldSchema("text", zvec.DataType.STRING),
            zvec.FieldSchema("search_text", zvec.DataType.STRING, index_param=zvec.FtsIndexParam(tokenizer_name="jieba")),
            zvec.FieldSchema("sha256", zvec.DataType.STRING),
            zvec.FieldSchema("lifecycle", zvec.DataType.STRING, index_param=zvec.InvertIndexParam()),
            zvec.FieldSchema("tier", zvec.DataType.STRING),
            zvec.FieldSchema("updated", zvec.DataType.STRING),
            zvec.FieldSchema("verified_at", zvec.DataType.STRING),
            zvec.FieldSchema("stale_after", zvec.DataType.STRING),
            zvec.FieldSchema("expires_at", zvec.DataType.STRING),
            zvec.FieldSchema("tags", zvec.DataType.STRING),
        ],
    )


def _zvec_doc(chunk: Chunk, zvec: Any) -> Any:
    return zvec.Doc(
        id=chunk.chunk_id,
        fields={
            "path": chunk.path,
            "page_id": chunk.page_id,
            "title": chunk.title,
            "summary": chunk.summary,
            "heading": chunk.heading_path,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "text": chunk.text,
            "search_text": chunk.search_text,
            "sha256": chunk.sha256,
            "lifecycle": chunk.lifecycle,
            "tier": chunk.tier,
            "updated": chunk.updated,
            "verified_at": chunk.verified_at,
            "stale_after": chunk.stale_after,
            "expires_at": chunk.expires_at,
            "tags": " ".join(chunk.tags),
        },
    )


def _build_zvec(chunks: list[Chunk], directory: Path) -> None:
    zvec = _load_zvec()
    store = directory / "store"
    collection = zvec.create_and_open(path=str(store), schema=_zvec_schema(zvec))
    try:
        for start in range(0, len(chunks), 500):
            statuses = collection.insert([_zvec_doc(chunk, zvec) for chunk in chunks[start:start + 500]])
            for status in (statuses if isinstance(statuses, list) else [statuses]):
                ok = getattr(status, "ok", None)
                if callable(ok):
                    ok = ok()
                if ok is None:
                    code = getattr(status, "code", None)
                    code = code() if callable(code) else code
                    ok = code in (None, 0)
                if not ok:
                    raise PackIndexError(f"zvec insert failed: {status}")
        flush = getattr(collection, "flush", None)
        if callable(flush):
            flush()
    finally:
        close = getattr(collection, "close", None)
        if callable(close):
            close()


def _zvec_search(
    index_dir: Path,
    query: str,
    *,
    topk: int,
    operator: str,
    include_archived: bool,
) -> list[dict[str, Any]]:
    zvec = _load_zvec()
    key = str(index_dir.resolve())
    collection = _ZVEC_COLLECTIONS.get(key)
    if collection is None:
        collection = zvec.open(
            str(index_dir / "store"),
            option=zvec.CollectionOption(read_only=True, enable_mmap=True),
        )
        _ZVEC_COLLECTIONS[key] = collection
    try:
        # zvec's match_string + default_operator disagrees with query_string for
        # three or more CJK terms, so multi-token queries use explicit boolean
        # operators. A single token keeps match_string's Jieba analysis.
        tokens = [token for token in query.split() if token]
        if len(tokens) > 1:
            joiner = " OR " if operator.upper() == "OR" else " AND "
            fts = zvec.Fts(query_string=joiner.join(tokens))
            parameter = None
        else:
            fts = zvec.Fts(match_string=query)
            parameter = zvec.FtsQueryParam(
                default_operator="OR" if operator.upper() == "OR" else "AND"
            )
        search = zvec.Query(field_name="search_text", fts=fts, param=parameter)
        docs = collection.query(
            queries=search,
            topk=max(topk * 5, topk),
            filter=None if include_archived else "lifecycle != 'archived'",
            output_fields=[
                "path", "page_id", "title", "heading", "line_start", "line_end",
                "text", "sha256", "lifecycle", "stale_after", "expires_at",
            ],
        )
        results = []
        for doc in docs:
            fields = getattr(doc, "fields", {}) or {}
            results.append(
                {
                    "chunk_id": doc.id,
                    "page_id": fields.get("page_id") or fields.get("path", ""),
                    "path": fields.get("path", ""),
                    "title": fields.get("title", ""),
                    "heading": fields.get("heading", ""),
                    "line_start": fields.get("line_start", 0),
                    "line_end": fields.get("line_end", 0),
                    "text": fields.get("text", ""),
                    "sha256": fields.get("sha256", ""),
                    "lifecycle": fields.get("lifecycle", ""),
                    "stale_after": fields.get("stale_after", ""),
                    "expires_at": fields.get("expires_at", ""),
                    "score": float(getattr(doc, "score", 0.0) or 0.0),
                }
            )
        return results
    except Exception:
        _ZVEC_COLLECTIONS.pop(key, None)
        raise


# ── Public query surface ────────────────────────────────────────────────────


def _today() -> str:
    return date.today().isoformat()


def _group_pages(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Collapse chunk hits to the best chunk per page, summing relevance."""
    grouped: dict[str, dict[str, Any]] = {}
    for item in results:
        path = str(item.get("path", ""))
        best = grouped.get(path)
        if best is None:
            grouped[path] = {"best": item, "score": float(item.get("score", 0.0)), "hits": 1}
            continue
        best["score"] += float(item.get("score", 0.0))
        best["hits"] += 1
        if float(item.get("score", 0.0)) > float(best["best"].get("score", 0.0)):
            best["best"] = item
    merged = []
    for path, entry in grouped.items():
        item = dict(entry["best"])
        item["score"] = entry["score"]
        item["hits"] = entry["hits"]
        item["path"] = path
        merged.append(item)
    merged.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("path", ""))))
    return merged[:limit]


def search_index(
    pack_dir: Path,
    query: str,
    *,
    engine: str | None = None,
    topk: int = 10,
    operator: str = "AND",
    include_archived: bool = False,
    include_expired: bool = False,
    group_pages: bool = True,
) -> dict[str, Any]:
    """Search a pack through one of its index sidecars."""
    pack_dir = Path(pack_dir)
    manifest = load_manifest(pack_dir)
    engines = available_indexes(pack_dir)
    if engine is None:
        engine = SQLITE_ENGINE if SQLITE_ENGINE in engines else (engines[0] if engines else None)
    if engine is None:
        raise PackIndexError("pack has no index; build one with `graph-wiki pack build --index sqlite`")
    engine = engine.lower()
    if engine not in ENGINES:
        raise PackIndexError(f"unknown index engine: {engine}")
    if engine not in engines:
        raise PackIndexError(f"pack has no {engine} index; build it first")
    meta = _load_meta(_index_dir(pack_dir, engine))
    if meta.get("content_pack_id") != manifest["pack_id"]:
        raise PackIndexError("index belongs to a different content pack; rebuild it")

    if engine in (SQLITE_ENGINE, SQLITE_SIMPLE_ENGINE):
        tokenizer = str(meta.get("config", {}).get("tokenizer") or engine_tokenizer(engine))
        if tokenizer in ("", "word+cjk-bigram"):
            tokenizer = "bigram"
        results = _sqlite_search(
            _index_dir(pack_dir, engine), query,
            topk=topk, operator=operator, include_archived=include_archived,
            tokenizer=tokenizer,
        )
    else:
        results = _zvec_search(
            _index_dir(pack_dir, engine), query,
            topk=topk, operator=operator, include_archived=include_archived,
        )

    today = _today()
    filtered = []
    for result in results:
        expired = str(result.get("expires_at", "")) and str(result["expires_at"]) < today
        if expired and not include_expired:
            continue
        result["stale"] = bool(result.get("stale_after")) and str(result["stale_after"]) < today
        result["text"] = str(result.get("text", ""))[:600]
        filtered.append(result)
    filtered.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("chunk_id", ""))))
    selected = _group_pages(filtered, topk) if group_pages else filtered[:topk]
    return {
        "pack_id": manifest["pack_id"],
        "version": manifest["version"],
        "engine": engine,
        "index_id": meta.get("index_id"),
        "query": query,
        "results": selected,
        "count": len(selected),
    }
