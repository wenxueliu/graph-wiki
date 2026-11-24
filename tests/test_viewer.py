"""Tests for the read-only viewer data model."""

from __future__ import annotations

from pathlib import Path

import pytest

from graph_wiki.viewer import (
    DEFAULT_PAGE_MAX_BYTES,
    GraphService,
    PageNotFound,
    build_graph_payload,
    load_page_payload,
    page_id_from_path,
)


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()

    _write(
        vault / "concepts/ml.md",
        """---
title: Machine Learning
category: concepts
tags: [ml, ai]
summary: The study of algorithms that improve through experience.
---
# ML
[[entities/nn|Neural Networks @implements]]
[[concepts/dl]]
""",
    )
    _write(
        vault / "concepts/dl.md",
        """---
title: Deep Learning
category: concepts
tags: [ml, deep-learning]
relationships:
  - target: "[[concepts/ml]]"
    type: parent_of
---
# DL
[[concepts/ml]] is the broader field.
""",
    )
    _write(
        vault / "entities/nn.md",
        """---
title: Neural Networks
category: entities
tags: [ml, architecture]
---
# NN
[[concepts/ml]] implemented via NNs.
""",
    )
    return vault


def _edge(payload: dict, source: str, target: str, relation: str) -> dict | None:
    return next(
        (
            edge
            for edge in payload["edges"]
            if edge["source"] == source
            and edge["target"] == target
            and edge["relation"] == relation
        ),
        None,
    )


class TestBuildGraphPayload:
    def test_uses_unique_path_ids(self, tmp_path: Path) -> None:
        payload = build_graph_payload(_make_vault(tmp_path))

        assert [node["id"] for node in payload["nodes"]] == [
            "concepts/dl",
            "concepts/ml",
            "entities/nn",
        ]
        assert payload["nodes"][0]["slug"] == "dl"
        assert payload["nodes"][1]["title"] == "Machine Learning"

    def test_keeps_typed_and_untyped_edges_separate(self, tmp_path: Path) -> None:
        payload = build_graph_payload(_make_vault(tmp_path))

        typed = _edge(payload, "concepts/ml", "entities/nn", "implements")
        assert typed is not None
        assert typed["typed"] is True
        assert typed["kind"] == "relationship"
        assert typed["representations"] == ["inline"]

        untyped = _edge(payload, "concepts/ml", "concepts/dl", "link")
        assert untyped is not None
        assert untyped["typed"] is False
        assert untyped["kind"] == "link"

    def test_skips_broken_links_and_self_links(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(
            vault / "concepts/broken.md",
            """---
title: Broken Links
category: concepts
tags: []
---
[[does-not-exist]]
[[concepts/broken]]
""",
        )
        payload = build_graph_payload(vault)

        targets = {edge["target"] for edge in payload["edges"]}
        assert "does-not-exist" not in targets
        assert all(
            not (edge["source"] == "concepts/broken" and edge["target"] == "concepts/broken")
            for edge in payload["edges"]
        )

    def test_degree_counts_unique_neighbours(self, tmp_path: Path) -> None:
        payload = build_graph_payload(_make_vault(tmp_path))
        nodes = {node["id"]: node for node in payload["nodes"]}

        assert nodes["concepts/ml"]["degree"] == 2
        assert nodes["concepts/ml"]["out_degree"] == 2
        assert nodes["concepts/ml"]["in_degree"] == 2
        assert nodes["concepts/dl"]["degree"] == 1
        assert nodes["entities/nn"]["degree"] == 1

    def test_stats_and_isolated_pages(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(
            vault / "concepts/lonely.md",
            """---
title: Lonely
category: concepts
tags: [misc]
---
No links here.
""",
        )
        payload = build_graph_payload(vault)

        assert payload["stats"]["pages"] == 4
        assert payload["stats"]["typed_edges"] == 2
        assert payload["stats"]["untyped_edges"] == 2
        assert payload["stats"]["isolated"] == ["concepts/lonely"]
        assert payload["stats"]["categories"]["concepts"] == 3

    def test_duplicate_slug_resolves_to_same_category(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(
            vault / "concepts/topic.md",
            """---
title: Concept Topic
category: concepts
tags: []
---
""",
        )
        _write(
            vault / "entities/topic.md",
            """---
title: Entity Topic
category: entities
tags: []
---
""",
        )
        _write(
            vault / "concepts/source.md",
            """---
title: Source
category: concepts
tags: []
---
[[topic]]
""",
        )
        payload = build_graph_payload(vault)

        edge = _edge(payload, "concepts/source", "concepts/topic", "link")
        assert edge is not None
        assert edge["ambiguous"] is True

    def test_excludes_root_bookkeeping_files(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(vault / "index.md", "# Index\n")
        _write(vault / "log.md", "# Log\n")
        _write(vault / "AGENTS.md", "# Rules\n")
        payload = build_graph_payload(vault)

        ids = {node["id"] for node in payload["nodes"]}
        assert "index" not in ids
        assert "log" not in ids
        assert "AGENTS" not in ids

    def test_excludes_nested_bootstrap_files_and_root_readme(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(vault / "README.md", "# Landing page\n")
        _write(vault / "concepts" / "AGENTS.md", "# Nested rules\n")
        payload = build_graph_payload(vault)

        ids = {node["id"] for node in payload["nodes"]}
        assert "README" not in ids
        assert "concepts/AGENTS" not in ids

    def test_payload_is_deterministic(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        first = build_graph_payload(vault)
        second = build_graph_payload(vault)

        assert first["nodes"] == second["nodes"]
        assert first["edges"] == second["edges"]
        assert first["vault"]["fingerprint"] == second["vault"]["fingerprint"]

    def test_does_not_write_vault_state(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        build_graph_payload(vault)

        assert not (vault / ".obsidian").exists()


def test_empty_vault_produces_an_empty_payload(tmp_path: Path) -> None:
    vault = tmp_path / "empty"
    vault.mkdir()
    payload = build_graph_payload(vault)

    assert payload["stats"]["pages"] == 0
    assert payload["stats"]["edges"] == 0
    assert payload["nodes"] == []
    assert payload["edges"] == []


class TestPagePayload:
    def test_reads_body_frontmatter_and_obsidian_uri(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        payload = load_page_payload(vault, "concepts/ml")

        assert payload["id"] == "concepts/ml"
        assert payload["content_trust"] == "untrusted_reference_data"
        assert "title: Machine Learning" in payload["frontmatter"]
        assert "# ML" in payload["body"]
        assert payload["obsidian_uri"].startswith("obsidian://open?path=")
        assert payload["truncated"] is False

    def test_truncates_large_bodies_at_the_requested_limit(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write(
            vault / "concepts/big.md",
            """---
title: Big
category: concepts
tags: []
---
"""
            + ("x" * 4_000),
        )
        payload = load_page_payload(vault, "concepts/big", max_bytes=1_024)

        assert payload["truncated"] is True
        assert payload["limit"] == 1_024
        assert payload["bytes"] > 1_024
        assert payload["body"].endswith("…")

    def test_unknown_page_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PageNotFound):
            load_page_payload(_make_vault(tmp_path), "concepts/missing")

    def test_path_outside_vault_raises(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        outside = _write(tmp_path / "outside.md", "---\ntitle: Outside\n---\n")
        node = {
            "id": "outside",
            "slug": "outside",
            "title": "Outside",
            "category": "",
            "tags": [],
            "summary": "",
            "path": "../" + outside.name,
        }

        with pytest.raises(PageNotFound):
            load_page_payload(vault, "outside", node=node)

    def test_default_limit_is_exposed(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        payload = load_page_payload(vault, "concepts/ml")
        assert payload["limit"] == DEFAULT_PAGE_MAX_BYTES


class TestGraphService:
    def test_reuses_payload_until_the_vault_changes(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        service = GraphService(vault, refresh_interval=0.0)

        first = service.graph()
        second = service.graph()
        assert first is second
        assert second["vault"]["fingerprint"] == first["vault"]["fingerprint"]

        _write(
            vault / "concepts/new.md",
            """---
title: New Page
category: concepts
tags: []
---
[[concepts/ml]]
""",
        )
        third = service.graph()
        assert third is not first
        assert third["vault"]["fingerprint"] != first["vault"]["fingerprint"]
        assert any(node["id"] == "concepts/new" for node in third["nodes"])

    def test_page_uses_cached_node(self, tmp_path: Path) -> None:
        service = GraphService(_make_vault(tmp_path))
        payload = service.page("concepts/ml")
        assert "# ML" in payload["body"]

    def test_unknown_page_raises(self, tmp_path: Path) -> None:
        service = GraphService(_make_vault(tmp_path))
        with pytest.raises(PageNotFound):
            service.page("nope")


def test_page_id_from_path() -> None:
    assert page_id_from_path("concepts/ml.md") == "concepts/ml"
    assert page_id_from_path("concepts/ml") == "concepts/ml"
