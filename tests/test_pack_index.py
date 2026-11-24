"""Pack index tests for SQLite FTS5 and the optional zvec backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_wiki.pack import build_pack
from graph_wiki.pack_chunks import segment_text
from graph_wiki.pack_index import build_index, search_index, sqlite_fts5_available


def write_page(
    vault: Path,
    relative: str,
    *,
    title: str,
    summary: str,
    body: str,
    lifecycle: str = "verified",
    extra: str = "",
) -> None:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"title: {title}\n"
        "category: concepts\n"
        "tags: [test]\n"
        "sources: [manual]\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        f"summary: {summary}\n"
        f"lifecycle: {lifecycle}\n"
        f"{extra}"
        "---\n"
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def make_pack(tmp_path: Path) -> tuple[Path, dict]:
    vault = tmp_path / "vault"
    write_page(
        vault,
        "concepts/retry.md",
        title="重试与退避",
        summary="指数退避与抖动，避免重试风暴。",
        body="## 退避策略\n\n指数退避与抖动避免重试风暴。\n\n## 一致性\n\n重试必须保证幂等。",
    )
    write_page(
        vault,
        "concepts/cache.md",
        title="缓存一致性",
        summary="缓存一致性需要版本号。",
        body="## 缓存\n\n缓存一致性需要版本号与失效策略。",
        lifecycle="archived",
    )
    manifest = build_pack(vault, store=tmp_path / "store")
    return tmp_path / "store" / manifest["vault_id"] / f"v{manifest['version']}", manifest


pytestmark = pytest.mark.skipif(
    not sqlite_fts5_available(), reason="sqlite3 was built without FTS5"
)


def test_sqlite_fts5_builds_and_searches_chinese(tmp_path: Path) -> None:
    pack_dir, manifest = make_pack(tmp_path)
    meta = build_index(pack_dir, "sqlite")
    assert meta["content_pack_id"] == manifest["pack_id"]
    assert build_index(pack_dir, "sqlite")["index_id"] == meta["index_id"]

    result = search_index(pack_dir, "重试 一致性", engine="sqlite")
    paths = [item["path"] for item in result["results"]]
    assert "concepts/retry.md" in paths
    assert "concepts/cache.md" not in paths


def test_simple_tokenizer_uses_chinese_unigrams() -> None:
    assert segment_text("重试", mode="simple", for_query=True) == ["重", "试"]
    assert "重试" in segment_text("重试", mode="bigram", for_query=True)


def test_sqlite_simple_engine_builds_and_searches(tmp_path: Path) -> None:
    pack_dir, _manifest = make_pack(tmp_path)
    meta = build_index(pack_dir, "sqlite-simple")
    assert meta["config"]["tokenizer"] == "simple"

    result = search_index(pack_dir, "重试", engine="sqlite-simple")
    assert result["engine"] == "sqlite-simple"
    assert "concepts/retry.md" in [item["path"] for item in result["results"]]


def test_sqlite_index_rejects_a_stale_content_pack(tmp_path: Path) -> None:
    pack_dir, manifest = make_pack(tmp_path)
    build_index(pack_dir, "sqlite")
    index_json = pack_dir / "indexes" / "sqlite" / "index.json"
    meta = json.loads(index_json.read_text(encoding="utf-8"))
    meta["content_pack_id"] = "sha256:" + "0" * 64
    index_json.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(Exception):
        search_index(pack_dir, "重试", engine="sqlite")


def test_expired_pages_are_excluded_by_default(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_page(
        vault,
        "concepts/old.md",
        title="过期条目",
        summary="已经过期的条目。",
        body="## 过期\n\n这段内容已经过期，但仍有检索价值。",
        extra="expires_at: 2025-01-01\n",
    )
    manifest = build_pack(vault, store=tmp_path / "store")
    pack_dir = tmp_path / "store" / manifest["vault_id"] / f"v{manifest['version']}"
    build_index(pack_dir, "sqlite")

    assert search_index(pack_dir, "过期", engine="sqlite")["results"] == []
    included = search_index(pack_dir, "过期", engine="sqlite", include_expired=True)
    assert included["results"]


def test_zvec_index_matches_the_sqlite_candidate(tmp_path: Path) -> None:
    pytest.importorskip("zvec")
    pack_dir, _manifest = make_pack(tmp_path)
    build_index(pack_dir, "sqlite")
    build_index(pack_dir, "zvec")

    sqlite_result = search_index(pack_dir, "重试 一致性", engine="sqlite")
    zvec_result = search_index(pack_dir, "重试 一致性", engine="zvec")

    assert sqlite_result["results"]
    assert zvec_result["results"]
    assert sqlite_result["results"][0]["path"] == "concepts/retry.md"
    assert all(item["path"] != "concepts/cache.md" for item in zvec_result["results"])
