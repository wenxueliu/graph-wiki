"""Read-only data model for the local graph viewer.

The viewer renders one page (``/``) from a single JSON payload.  That payload
is also the only data source the browser needs: nodes carry their frontmatter
summary, tags, category, path, and degree, and edges carry the typed
relationship identity.  Clicking a node reads the matching Markdown body
through :class:`GraphService.page`.

Nothing here writes to the vault.  The page index is built in memory, and the
payload is cached by a ``(path, mtime_ns, size)`` fingerprint so a running
server notices edits without rebuilding on every request.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from graph_wiki.index import build_page_index, entry_edges
from graph_wiki.page_set import page_files as _shared_page_files
from graph_wiki.relationships import split_frontmatter

SCHEMA_VERSION = 1
DEFAULT_PAGE_MAX_BYTES = 256_000
MAX_PAGE_MAX_BYTES = 2_000_000
CONTENT_TRUST = "untrusted_reference_data"

class ViewerError(RuntimeError):
    """Base error for viewer data operations."""


class PageNotFound(ViewerError):
    """The requested page id is not part of the current vault graph."""


def page_id_from_path(relative_path: str) -> str:
    """Return the stable viewer id for a vault-relative Markdown path."""
    return relative_path[:-3] if relative_path.endswith(".md") else relative_path


def _resolved_vault(vault: str | Path) -> Path:
    return Path(vault).expanduser().resolve()


def _relative(path: Path, vault: Path) -> str:
    return path.relative_to(vault).as_posix()


def _fingerprint(vault: Path, files: Iterable[Path]) -> str:
    """Hash the stat identity of every page file.

    Content is not read here: mtime_ns + size is the same invalidation signal
    the shared index uses, and a stat is cheap enough for a local viewer.
    """
    digest = hashlib.sha256()
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(
            (
                f"{_relative(path, vault)}\0{stat.st_mtime_ns}\0{stat.st_size}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def _resolve_target(
    source_id: str,
    target_slug: str,
    slug_to_ids: dict[str, list[str]],
    nodes_by_id: dict[str, dict[str, Any]],
) -> tuple[str, bool] | None:
    """Resolve a wikilink slug to one unique page id.

    Wikilinks are basename-addressed while viewer ids are vault-relative, so
    two files with the same stem are possible.  Prefer the target in the
    source page's category, then fall back to the lexicographically first id.
    The returned flag tells the caller the resolution was ambiguous.
    """
    candidates = slug_to_ids.get(target_slug, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0], False

    source_category = nodes_by_id.get(source_id, {}).get("category", "")
    same_category = sorted(
        candidate
        for candidate in candidates
        if nodes_by_id.get(candidate, {}).get("category") == source_category
    )
    chosen = (same_category or sorted(candidates))[0]
    return chosen, True


def _build_payload(vault: Path, files: list[Path], fingerprint: str) -> dict[str, Any]:
    allowed = {_relative(path, vault) for path in files}
    raw_index: dict[str, dict[str, Any]] = {}
    for relative, entry in build_page_index(vault).items():
        # The shared index keys with ``str(relative)``; normalise Windows
        # separators so the fingerprint and page ids stay POSIX-shaped.
        normalised = relative.replace("\\", "/")
        if normalised in allowed:
            raw_index[normalised] = entry

    nodes: list[dict[str, Any]] = []
    nodes_by_id: dict[str, dict[str, Any]] = {}
    slug_to_ids: dict[str, list[str]] = defaultdict(list)

    for relative, entry in raw_index.items():
        node_id = page_id_from_path(relative)
        title = str(entry.get("title") or node_id)
        node = {
            "id": node_id,
            "slug": str(entry.get("slug") or Path(relative).stem),
            "label": title,
            "title": title,
            "category": str(entry.get("category") or ""),
            "tags": [str(tag) for tag in entry.get("tags", [])],
            "summary": str(entry.get("summary") or ""),
            "path": relative,
            "tier": str(entry.get("tier") or "supporting"),
            "lifecycle": str(entry.get("lifecycle") or ""),
            "operational_state": str(entry.get("operational_state") or ""),
            "degree": 0,
            "in_degree": 0,
            "out_degree": 0,
        }
        nodes.append(node)
        nodes_by_id[node_id] = node
        slug_to_ids[node["slug"]].append(node_id)

    nodes.sort(key=lambda node: node["id"])

    edges_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
    for relative, entry in raw_index.items():
        source_id = page_id_from_path(relative)
        for edge in entry_edges(entry):
            target_slug = str(edge.get("target") or "")
            if not target_slug:
                continue
            resolved = _resolve_target(source_id, target_slug, slug_to_ids, nodes_by_id)
            if resolved is None:
                continue
            target_id, ambiguous = resolved
            if target_id == source_id or target_id not in nodes_by_id:
                continue

            relation = str(edge.get("relation") or "link")
            typed = bool(edge.get("typed", False))
            identity = (source_id, target_id, relation)
            existing = edges_by_identity.get(identity)
            if existing is not None:
                existing["weight"] += int(edge.get("weight", 1) or 1)
                for representation in edge.get("representations", []):
                    if representation not in existing["representations"]:
                        existing["representations"].append(representation)
                existing["ambiguous"] = bool(existing["ambiguous"] or ambiguous)
                continue

            edges_by_identity[identity] = {
                "id": f"{source_id}|{target_id}|{relation}",
                "source": source_id,
                "target": target_id,
                "relation": relation,
                "kind": str(
                    edge.get("kind") or ("relationship" if typed else "link")
                ),
                "typed": typed,
                "weight": int(edge.get("weight", 1) or 1),
                "representations": [
                    str(representation)
                    for representation in edge.get("representations", [])
                ],
                "ambiguous": ambiguous,
            }

    edges = sorted(
        edges_by_identity.values(),
        key=lambda edge: (edge["source"], edge["target"], edge["relation"]),
    )

    out_neighbors: dict[str, set[str]] = defaultdict(set)
    in_neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        out_neighbors[edge["source"]].add(edge["target"])
        in_neighbors[edge["target"]].add(edge["source"])

    for node in nodes:
        node_id = node["id"]
        node["out_degree"] = len(out_neighbors.get(node_id, ()))
        node["in_degree"] = len(in_neighbors.get(node_id, ()))
        node["degree"] = len(
            out_neighbors.get(node_id, set()) | in_neighbors.get(node_id, set())
        )

    category_counts = Counter(node["category"] or "(none)" for node in nodes)
    tag_counts: Counter[str] = Counter()
    for node in nodes:
        tag_counts.update(node["tags"])

    page_count = len(nodes)
    typed_edges = sum(1 for edge in edges if edge["typed"])
    density = (
        round(len(edges) / (page_count * (page_count - 1)), 6)
        if page_count > 1
        else 0.0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vault": {
            "name": vault.name or str(vault),
            "path": str(vault),
            "fingerprint": fingerprint,
        },
        "stats": {
            "pages": page_count,
            "edges": len(edges),
            "typed_edges": typed_edges,
            "untyped_edges": len(edges) - typed_edges,
            "density": density,
            "categories": dict(sorted(category_counts.items())),
            "tags": dict(sorted(tag_counts.items())),
            "isolated": sorted(
                node["id"] for node in nodes if node["degree"] == 0
            ),
        },
        "nodes": nodes,
        "edges": edges,
    }


def build_graph_payload(vault: str | Path) -> dict[str, Any]:
    """Build the complete viewer payload for *vault* without writing anything."""
    resolved = _resolved_vault(vault)
    files = _shared_page_files(resolved)
    return _build_payload(resolved, files, _fingerprint(resolved, files))


def _find_node(payload: dict[str, Any], page_id: str) -> dict[str, Any] | None:
    for node in payload["nodes"]:
        if node["id"] == page_id:
            return node
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def load_page_payload(
    vault: str | Path,
    page_id: str,
    *,
    max_bytes: int = DEFAULT_PAGE_MAX_BYTES,
    node: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one page body for the detail sidebar.

    The caller normally passes the node from the cached payload.  Without it
    the payload is rebuilt, which keeps this helper usable in tests and from a
    one-shot call.
    """
    resolved = _resolved_vault(vault)
    if node is None:
        node = _find_node(build_graph_payload(resolved), page_id)
    if node is None:
        raise PageNotFound(f"page not found: {page_id}")

    relative = str(node.get("path") or "")
    absolute = (resolved / relative).resolve()
    if not relative or not _is_within(absolute, resolved):
        raise PageNotFound(f"page not found: {page_id}")

    try:
        text = absolute.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PageNotFound(f"page not found: {page_id}") from exc

    limit = max(1_024, min(int(max_bytes), MAX_PAGE_MAX_BYTES))
    frontmatter, body = split_frontmatter(text)
    body_bytes = body.encode("utf-8")
    truncated = len(body_bytes) > limit
    if truncated:
        body = body_bytes[:limit].decode("utf-8", errors="replace") + "\n\n…"

    return {
        "schema_version": SCHEMA_VERSION,
        "content_trust": CONTENT_TRUST,
        "id": page_id,
        "slug": node.get("slug", ""),
        "title": node.get("title", page_id),
        "category": node.get("category", ""),
        "tags": list(node.get("tags", [])),
        "summary": node.get("summary", ""),
        "path": relative,
        "frontmatter": frontmatter,
        "body": body,
        "bytes": len(body_bytes),
        "limit": limit,
        "truncated": truncated,
        "obsidian_uri": "obsidian://open?path=" + quote(str(absolute)),
    }


class GraphService:
    """Thread-safe, read-only payload cache for one vault."""

    def __init__(self, vault: str | Path, *, refresh_interval: float = 1.0) -> None:
        self.vault = _resolved_vault(vault)
        self.refresh_interval = max(0.0, float(refresh_interval))
        self._lock = threading.RLock()
        self._payload: dict[str, Any] | None = None
        self._fingerprint = ""
        self._nodes_by_id: dict[str, dict[str, Any]] = {}
        self._checked_at = 0.0

    def _refresh_locked(self) -> dict[str, Any]:
        now = time.monotonic()
        if (
            self._payload is not None
            and (now - self._checked_at) < self.refresh_interval
        ):
            return self._payload

        files = _shared_page_files(self.vault)
        fingerprint = _fingerprint(self.vault, files)
        if self._payload is None or fingerprint != self._fingerprint:
            payload = _build_payload(self.vault, files, fingerprint)
            self._payload = payload
            self._fingerprint = fingerprint
            self._nodes_by_id = {
                node["id"]: node for node in payload["nodes"]
            }
        self._checked_at = now
        return self._payload

    def graph(self) -> dict[str, Any]:
        with self._lock:
            return self._refresh_locked()

    def page(
        self, page_id: str, *, max_bytes: int = DEFAULT_PAGE_MAX_BYTES
    ) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            node = self._nodes_by_id.get(page_id)
        if node is None:
            raise PageNotFound(f"page not found: {page_id}")
        return load_page_payload(
            self.vault, page_id, max_bytes=max_bytes, node=node
        )
