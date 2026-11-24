"""Evaluate pack retrieval engines against a fixed query set.

The query set is deliberately plain JSON so it can live next to a vault, be
reviewed like code, and be replayed against any pack version:

    {
      "name": "core-cn",
      "k": 5,
      "queries": [
        {"id": "retry", "query": "重试 一致性", "expect": ["concepts/retry.md"]}
      ]
    }

Metrics are page-level and binary-relevance: recall@k, hit@k, MRR@k, and
nDCG@k. Engines are compared independently; their BM25 scores are not.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from graph_wiki.pack import PackError, load_manifest
from graph_wiki.pack_index import available_indexes, search_index


class PackEvalError(PackError):
    """A query set or evaluation run is invalid."""


def load_query_set(path: Path) -> dict[str, Any]:
    """Load a JSON or JSONL query set and validate its shape."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackEvalError(f"cannot read query set: {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = {"queries": [json.loads(line) for line in text.splitlines() if line.strip()]}
        except json.JSONDecodeError as exc:
            raise PackEvalError(f"query set is not valid JSON or JSONL: {path}") from exc
    if isinstance(data, list):
        data = {"queries": data}
    if not isinstance(data, dict):
        raise PackEvalError("query set must be a JSON object or array")
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        raise PackEvalError("query set must contain a non-empty queries array")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(queries):
        if not isinstance(item, dict):
            raise PackEvalError(f"query #{index + 1} must be an object")
        query = str(item.get("query", "")).strip()
        if not query:
            raise PackEvalError(f"query #{index + 1} has no query text")
        expected = item.get("expect", item.get("expected", []))
        if not isinstance(expected, list) or not all(isinstance(path, str) for path in expected):
            raise PackEvalError(f"query #{index + 1} expect must be a string array")
        normalized.append(
            {
                "id": str(item.get("id") or f"q{index + 1}"),
                "query": query,
                "expect": list(expected),
            }
        )

    k = data.get("k", 5)
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise PackEvalError("query set k must be a positive integer")
    return {
        "name": str(data.get("name") or path.stem),
        "k": k,
        "queries": normalized,
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def _score_query(retrieved: list[str], expected: list[str], k: int) -> dict[str, float]:
    expected_set = set(expected)
    matches = [path for path in retrieved[:k] if path in expected_set]
    unique_matches = set(matches)
    recall = len(unique_matches) / len(expected_set) if expected_set else 0.0
    hit = 1.0 if unique_matches else 0.0
    mrr = 0.0
    for rank, path in enumerate(retrieved[:k], start=1):
        if path in expected_set:
            mrr = 1.0 / rank
            break
    dcg = sum(1.0 / math.log2(rank + 1) for rank, path in enumerate(retrieved[:k], start=1) if path in expected_set)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(expected_set), k) + 1))
    ndcg = dcg / ideal if ideal else 0.0
    return {
        "recall": round(recall, 4),
        "hit": round(hit, 4),
        "mrr": round(mrr, 4),
        "ndcg": round(ndcg, 4),
    }


def evaluate_pack(
    pack_dir: Path,
    query_set: dict[str, Any],
    *,
    engines: list[str] | None = None,
    k: int | None = None,
) -> dict[str, Any]:
    """Run one query set against every requested (or available) index."""
    pack_dir = Path(pack_dir)
    manifest = load_manifest(pack_dir)
    built = available_indexes(pack_dir)
    if not built:
        raise PackEvalError("pack has no indexes; build one before evaluating")
    selected = [engine for engine in (engines or built) if engine in built]
    if not selected:
        raise PackEvalError("none of the requested engines has an index")
    queries = query_set["queries"]
    topk = k or int(query_set["k"])

    report: dict[str, Any] = {
        "pack_id": manifest["pack_id"],
        "version": manifest["version"],
        "name": query_set["name"],
        "k": topk,
        "queries": len(queries),
        "engines": {},
    }
    for engine in selected:
        details = []
        latencies: list[float] = []
        try:
            # Warm the engine (native init/open) before measuring.
            search_index(pack_dir, queries[0]["query"], engine=engine, topk=topk)
        except PackError as exc:
            raise PackEvalError(f"{engine}: {exc}") from exc
        for item in queries:
            started = time.perf_counter()
            try:
                result = search_index(
                    pack_dir,
                    item["query"],
                    engine=engine,
                    topk=topk,
                )
            except PackError as exc:
                raise PackEvalError(f"{engine} / {item['id']}: {exc}") from exc
            latency = (time.perf_counter() - started) * 1000
            latencies.append(latency)
            retrieved = [str(hit["path"]) for hit in result["results"]]
            scores = _score_query(retrieved, item["expect"], topk)
            details.append(
                {
                    "id": item["id"],
                    "query": item["query"],
                    "expect": item["expect"],
                    "retrieved": retrieved,
                    "latency_ms": round(latency, 3),
                    **scores,
                }
            )
        count = len(details)
        report["engines"][engine] = {
            "queries": count,
            "recall_at_k": round(sum(item["recall"] for item in details) / count, 4),
            "hit_at_k": round(sum(item["hit"] for item in details) / count, 4),
            "mrr_at_k": round(sum(item["mrr"] for item in details) / count, 4),
            "ndcg_at_k": round(sum(item["ndcg"] for item in details) / count, 4),
            "latency_ms_p50": _percentile(latencies, 0.50),
            "latency_ms_p95": _percentile(latencies, 0.95),
            "details": details,
        }
    return report
