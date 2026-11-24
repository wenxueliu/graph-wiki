"""Evaluation harness tests for pack retrieval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_wiki.pack import build_pack
from graph_wiki.pack_eval import PackEvalError, evaluate_pack, load_query_set
from graph_wiki.pack_index import build_index, sqlite_fts5_available


def write_page(vault: Path, relative: str, *, title: str, summary: str, body: str, lifecycle: str = "verified") -> None:
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
        "---\n"
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


pytestmark = pytest.mark.skipif(
    not sqlite_fts5_available(), reason="sqlite3 was built without FTS5"
)


def make_pack(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    write_page(
        vault,
        "concepts/retry.md",
        title="重试与退避",
        summary="指数退避与抖动。",
        body="## 一致性\n\n重试必须保证幂等。",
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
    return tmp_path / "store" / manifest["vault_id"] / f"v{manifest['version']}"


def test_evaluate_compares_built_engines(tmp_path: Path) -> None:
    pack_dir = make_pack(tmp_path)
    build_index(pack_dir, "sqlite")
    build_index(pack_dir, "sqlite-simple")
    query_set = {
        "name": "smoke",
        "k": 3,
        "queries": [
            {"id": "retry", "query": "重试 一致性", "expect": ["concepts/retry.md"]},
            {"id": "cache", "query": "缓存 一致性", "expect": ["concepts/cache.md"]},
        ],
    }

    report = evaluate_pack(pack_dir, query_set)

    assert set(report["engines"]) == {"sqlite", "sqlite-simple"}
    for engine in ("sqlite", "sqlite-simple"):
        result = report["engines"][engine]
        assert result["queries"] == 2
        assert result["recall_at_k"] == 0.5
        assert result["details"][0]["recall"] == 1.0
        assert result["details"][1]["recall"] == 0.0


def test_load_query_set_accepts_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"id": "a", "query": "检索", "expect": ["concepts/a.md"]}),
                json.dumps({"id": "b", "query": "向量", "expect": ["concepts/b.md"]}),
            ]
        ),
        encoding="utf-8",
    )
    query_set = load_query_set(path)
    assert [item["id"] for item in query_set["queries"]] == ["a", "b"]
    assert query_set["k"] == 5


def test_load_query_set_rejects_empty_queries(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"queries": []}', encoding="utf-8")
    with pytest.raises(PackEvalError):
        load_query_set(path)
