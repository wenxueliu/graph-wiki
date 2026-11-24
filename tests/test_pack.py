"""Deterministic content-pack tests (stdlib only)."""

from __future__ import annotations

from pathlib import Path

from graph_wiki.pack import (
    build_pack,
    diff_packs,
    list_packs,
    load_manifest,
    materialize,
    verify_pack,
)


def write_page(
    vault: Path,
    relative: str,
    *,
    title: str,
    summary: str,
    body: str = "",
    tags: tuple[str, ...] = ("test",),
    lifecycle: str = "verified",
    updated: str = "2026-01-01",
    extra: str = "",
) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    tag_text = ", ".join(tags)
    text = (
        "---\n"
        f"title: {title}\n"
        "category: concepts\n"
        f"tags: [{tag_text}]\n"
        "sources: [manual]\n"
        "created: 2026-01-01\n"
        f"updated: {updated}\n"
        f"summary: {summary}\n"
        f"lifecycle: {lifecycle}\n"
        f"{extra}"
        "---\n"
        f"# {title}\n\n{body or summary}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


def test_pack_build_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_page(vault, "concepts/retry.md", title="Retry", summary="Retry with backoff.")
    store = tmp_path / "store"

    first = build_pack(vault, store=store)
    second = build_pack(vault, store=store)

    assert first["pack_id"] == second["pack_id"]
    assert first["version"] == second["version"] == 1
    assert len(list_packs(store, first["vault_id"])) == 1
    assert verify_pack(store / first["vault_id"] / "v1")["ok"]


def test_pack_diff_and_verify_detect_changes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    page = write_page(vault, "concepts/retry.md", title="Retry", summary="Retry with backoff.")
    store = tmp_path / "store"

    first = build_pack(vault, store=store)
    page.write_text(page.read_text(encoding="utf-8") + "\nAdd jitter.\n", encoding="utf-8")
    second = build_pack(vault, store=store)

    assert second["version"] == 2
    assert first["pack_id"] != second["pack_id"]
    base = store / second["vault_id"]
    report = diff_packs(base / "v1", base / "v2")
    assert report["updated"] == ["concepts/retry.md"]


def test_pack_verify_rejects_a_tampered_body(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_page(vault, "concepts/retry.md", title="Retry", summary="Retry with backoff.")
    store = tmp_path / "store"
    manifest = build_pack(vault, store=store)
    pack_dir = store / manifest["vault_id"] / "v1"

    report = verify_pack(pack_dir)
    assert report["ok"]

    inventory = (pack_dir / "inventory.jsonl").read_text(encoding="utf-8").strip()
    import json

    entry = json.loads(inventory.splitlines()[0])
    body = pack_dir / "bodies" / f"{entry['sha256'].removeprefix('sha256:')}.md"
    body.write_text("tampered", encoding="utf-8")

    assert not verify_pack(pack_dir)["ok"]


def test_visibility_filter_excludes_pages(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_page(vault, "concepts/public.md", title="Public", summary="Public note.")
    write_page(
        vault,
        "concepts/secret.md",
        title="Secret",
        summary="Internal note.",
        tags=("test", "visibility/internal"),
    )
    store = tmp_path / "store"
    manifest = build_pack(vault, store=store, visibility_filter=["visibility/internal"])
    pack_dir = store / manifest["vault_id"] / "v1"
    inventory = (pack_dir / "inventory.jsonl").read_text(encoding="utf-8")

    assert "concepts/public.md" in inventory
    assert "concepts/secret.md" not in inventory
    edges = (pack_dir / "edges.jsonl").read_text(encoding="utf-8")
    assert "secret" not in edges


def test_materialize_writes_a_grep_tree(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_page(vault, "concepts/retry.md", title="Retry", summary="Retry with backoff.")
    store = tmp_path / "store"
    manifest = build_pack(vault, store=store)
    pack_dir = store / manifest["vault_id"] / "v1"
    destination = tmp_path / "snapshot"

    result = materialize(pack_dir, destination)

    assert result["pages"] == 1
    assert (destination / "concepts" / "retry.md").is_file()
    assert load_manifest(pack_dir)["pack_id"] == manifest["pack_id"]


def test_stale_after_uses_the_freshness_policy(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_page(
        vault,
        "concepts/old.md",
        title="Old",
        summary="Old note.",
        updated="2025-01-01",
    )
    store = tmp_path / "store"
    manifest = build_pack(vault, store=store, max_age_days=30)
    pack_dir = store / manifest["vault_id"] / "v1"
    import json

    entry = json.loads((pack_dir / "inventory.jsonl").read_text(encoding="utf-8").strip())
    assert entry["stale_after"] == "2025-01-31"
    assert manifest["counts"]["stale"] == 1
