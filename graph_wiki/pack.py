"""Deterministic, immutable knowledge packs derived from a vault.

A pack is a read model: the vault stays the only writable source of truth.
Everything here is pure-stdlib so ``pack build`` and ``pack verify`` keep
working without an index engine installed.

Layout under ``<store>/<vault_id>/``::

    v42/
        manifest.json
        inventory.jsonl
        edges.jsonl
        bodies/<sha256>.md
        indexes/<engine>/...      # built by graph_wiki.pack_index
    channels/release.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from graph_wiki import __version__, config_paths
from graph_wiki.index import build_page_index, entry_edges
from graph_wiki.knowledge_pack import active_knowledge_pack
from graph_wiki.relationships import split_frontmatter


PACK_FORMAT = 1
DEFAULT_CHANNEL = "release"
DEFAULT_MAX_AGE_DAYS = 90
POLICY_FILE = Path("_meta") / "pack-policy.json"
STATE_FILES = ("index.md", "hot.md", ".manifest.json")
_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class PackError(RuntimeError):
    """A pack could not be built, resolved, or verified."""


def default_store() -> Path:
    """Return the default pack store inside the resolved config directory."""
    return config_paths.resolve_config_dir(default=Path.home() / ".graph-wiki") / "packs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _normalise_text(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_text(path: Path) -> str:
    return _normalise_text(path.read_text(encoding="utf-8", errors="replace"))


def _iso_date(value: str) -> date | None:
    match = _DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _frontmatter_value(front: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*?)\s*$", front, re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip().strip("'\"")
    return "" if value in ("", "null", "~") else value


def _nested_value(front: str, parent: str, key: str) -> str:
    block = re.search(
        rf"^{re.escape(parent)}:\s*\n((?:[ \t]+.*(?:\n|$))+)",
        front,
        re.MULTILINE,
    )
    if not block:
        return ""
    match = re.search(rf"^\s+{re.escape(key)}:\s*(.*?)\s*$", block.group(1), re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip().strip("'\"")
    return "" if value in ("", "null", "~") else value


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return cleaned[:64] or "vault"


def _git(vault: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(vault), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def load_policy(vault: Path) -> dict[str, Any]:
    """Read ``_meta/pack-policy.json`` with conservative defaults."""
    vault = Path(vault)
    policy: dict[str, Any] = {}
    path = vault / POLICY_FILE
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PackError(f"invalid pack policy: {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise PackError(f"pack policy must be a JSON object: {path}")
        policy = loaded
    max_age = policy.get("default_max_age_days", DEFAULT_MAX_AGE_DAYS)
    if not isinstance(max_age, int) or isinstance(max_age, bool) or max_age < 1:
        raise PackError("pack policy default_max_age_days must be a positive integer")
    filters = policy.get("visibility_filter", [])
    if not isinstance(filters, list) or not all(isinstance(item, str) for item in filters):
        raise PackError("pack policy visibility_filter must be a string array")
    return {
        "vault_id": str(policy.get("vault_id") or "").strip(),
        "default_max_age_days": max_age,
        "visibility_filter": list(filters),
    }


def vault_identity(vault: Path, policy: dict[str, Any] | None = None) -> str:
    """Stable per-vault identifier: explicit policy, git remote, then path."""
    vault = Path(vault).expanduser().resolve()
    policy = policy if policy is not None else load_policy(vault)
    explicit = policy.get("vault_id", "")
    if explicit:
        return _safe_id(str(explicit))
    remote = _git(vault, "remote", "get-url", "origin")
    if remote:
        return "git-" + hashlib.sha256(remote.encode("utf-8")).hexdigest()[:12]
    return "vault-" + hashlib.sha256(str(vault).encode("utf-8")).hexdigest()[:12]


def _git_state(vault: Path) -> tuple[str | None, bool]:
    commit = _git(vault, "rev-parse", "HEAD")
    status = _git(vault, "status", "--porcelain")
    return commit, bool(status)


def _file_hash(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def pack_contracts(vault: Path) -> dict[str, str]:
    """Bind a pack to the active Knowledge Pack's contract hashes."""
    pack = active_knowledge_pack(Path(vault))
    root = pack.root
    contracts = {
        "knowledge_pack": pack.name,
        "profile_sha256": _file_hash(root / "profile.json"),
        "layout_sha256": _file_hash(root / "layout.json"),
        "routing_rules_sha256": _file_hash(root / "routing.json"),
        "routing_prompt_sha256": _file_hash(root / "routing.md"),
    }
    missing = [key for key, value in contracts.items() if key.endswith("_sha256") and not value]
    if missing:
        raise PackError("Knowledge Pack contract is incomplete: " + ", ".join(missing))
    return contracts


def _relative_slug(value: str) -> str:
    return Path(value).stem.strip().lower().replace(" ", "-")


def _stale_after(updated: str, verified: str, max_age_days: int) -> str:
    candidates = [parsed for parsed in (_iso_date(updated), _iso_date(verified)) if parsed]
    if not candidates:
        return ""
    return (max(candidates) + timedelta(days=max_age_days)).isoformat()


def _counts(inventory: list[dict[str, Any]]) -> dict[str, int]:
    today = date.today()
    stale = sum(1 for entry in inventory if entry.get("stale_after") and entry["stale_after"] < today.isoformat())
    expired = sum(1 for entry in inventory if entry.get("expires_at") and entry["expires_at"] < today.isoformat())
    archived = sum(1 for entry in inventory if str(entry.get("lifecycle", "")).lower() in {"archived", "sunset"})
    return {
        "pages": len(inventory),
        "stale": stale,
        "expired": expired,
        "archived": archived,
    }


def _build_inventory(
    vault: Path,
    pages: dict[str, dict[str, Any]],
    max_age_days: int,
    visibility_filter: Iterable[str],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    blocked = {tag.strip() for tag in visibility_filter if tag.strip()}
    inventory: list[dict[str, Any]] = []
    bodies: dict[str, str] = {}
    for relative in sorted(pages):
        entry = pages[relative]
        if blocked and blocked.intersection({str(tag) for tag in entry.get("tags", [])}):
            continue
        path = vault / relative
        try:
            text = _read_text(path)
        except OSError as exc:
            raise PackError(f"cannot read page {relative}: {exc}") from exc
        front, _body = split_frontmatter(text)
        updated = _frontmatter_value(front, "updated")
        verified = _nested_value(front, "verification", "verified_at") or _frontmatter_value(front, "verified_at")
        expires = _frontmatter_value(front, "expires_at") or _frontmatter_value(front, "valid_until")
        sha = _sha256_text(text)
        bodies[sha] = text
        inventory.append(
            {
                "path": relative,
                "sha256": sha,
                "title": str(entry.get("title", "")),
                "summary": str(entry.get("summary", "")),
                "tags": [str(tag) for tag in entry.get("tags", [])],
                "lifecycle": str(entry.get("lifecycle", "")).lower(),
                "operational_state": str(entry.get("operational_state", "")).lower(),
                "tier": str(entry.get("tier", "supporting")),
                "updated": updated,
                "verified_at": verified,
                "stale_after": _stale_after(updated, verified, max_age_days),
                "expires_at": (_iso_date(expires).isoformat() if _iso_date(expires) else ""),
            }
        )
    return inventory, bodies


def _build_edges(
    pages: dict[str, dict[str, Any]],
    allowed: set[str] | None = None,
) -> list[dict[str, Any]]:
    by_slug: dict[str, str] = {}
    for relative in sorted(pages):
        if allowed is not None and relative not in allowed:
            continue
        by_slug.setdefault(_relative_slug(relative), relative)
    seen: set[tuple[str, str, str]] = set()
    edges: list[dict[str, Any]] = []
    for relative in sorted(pages):
        if allowed is not None and relative not in allowed:
            continue
        for edge in entry_edges(pages[relative]):
            target = by_slug.get(_relative_slug(str(edge.get("target", ""))))
            if not target or target == relative:
                continue
            kind = str(edge.get("relation") or edge.get("type") or "link")
            key = (relative, target, kind)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from": relative,
                    "to": target,
                    "type": kind,
                    "typed": bool(edge.get("typed")),
                }
            )
    return sorted(edges, key=lambda item: (item["from"], item["to"], item["type"]))


def _pack_identity(
    vault_id: str,
    contracts: dict[str, str],
    visibility_filter: list[str],
    max_age_days: int,
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    fields = ("path", "sha256", "lifecycle", "updated", "verified_at", "stale_after", "expires_at", "tier")
    return {
        "pack_format": PACK_FORMAT,
        "vault_id": vault_id,
        "contracts": contracts,
        "visibility_filter": sorted(visibility_filter),
        "max_age_days": max_age_days,
        "pages": [{key: entry.get(key, "") for key in fields} for entry in inventory],
    }


def _pack_id(identity: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical_json(identity))


def _jsonl(rows: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _versions(base: Path) -> list[int]:
    if not base.is_dir():
        return []
    versions = []
    for child in base.iterdir():
        if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
            versions.append(int(child.name[1:]))
    return sorted(versions)


def load_manifest(pack_dir: Path) -> dict[str, Any]:
    path = Path(pack_dir) / "manifest.json"
    if not path.is_file():
        raise PackError(f"not a pack: {pack_dir}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError(f"invalid pack manifest: {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("pack_format") != PACK_FORMAT:
        raise PackError(f"unsupported pack format: {path}")
    return value


def _load_inventory(pack_dir: Path) -> list[dict[str, Any]]:
    path = Path(pack_dir) / "inventory.jsonl"
    if not path.is_file():
        raise PackError(f"pack inventory is missing: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _channel_pointer(base: Path, channel: str) -> dict[str, Any] | None:
    path = base / "channels" / f"{channel}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_channel(base: Path, channel: str, manifest: dict[str, Any]) -> None:
    pointer = {
        "channel": channel,
        "pack_id": manifest["pack_id"],
        "version": manifest["version"],
        "updated_at": _now(),
    }
    _atomic_write(base / "channels" / f"{channel}.json", json.dumps(pointer, ensure_ascii=False, indent=2) + "\n")


def build_pack(
    vault: Path,
    *,
    store: Path | None = None,
    channel: str = DEFAULT_CHANNEL,
    allow_dirty: bool = False,
    max_age_days: int | None = None,
    visibility_filter: list[str] | None = None,
    version: int | None = None,
) -> dict[str, Any]:
    """Build one immutable content pack from the vault's current pages."""
    vault = Path(vault).expanduser().resolve()
    if not vault.is_dir():
        raise PackError(f"vault not found: {vault}")
    policy = load_policy(vault)
    store = Path(store).expanduser().resolve() if store else default_store()
    identity = vault_identity(vault, policy)
    contracts = pack_contracts(vault)
    commit, dirty = _git_state(vault)
    if dirty and not allow_dirty:
        raise PackError("vault has uncommitted changes; commit them or pass --allow-dirty")

    age = max_age_days if max_age_days is not None else int(policy["default_max_age_days"])
    if age < 1:
        raise PackError("max_age_days must be positive")
    filters = visibility_filter if visibility_filter is not None else list(policy["visibility_filter"])

    pages = build_page_index(vault)
    inventory, bodies = _build_inventory(vault, pages, age, filters)
    edges = _build_edges(pages, {entry["path"] for entry in inventory})

    pack_id = _pack_id(_pack_identity(identity, contracts, filters, age, inventory))
    base = store / identity
    base.mkdir(parents=True, exist_ok=True)

    # Rebuilding unchanged knowledge is a no-op: the content id is the version.
    # ``created_at``/``freshness`` are deliberately excluded from ``pack_id``,
    # so a later build of identical pages returns the existing version.
    if version is None:
        existing_versions = _versions(base)
        if existing_versions:
            latest = load_manifest(base / f"v{existing_versions[-1]}")
            if latest.get("pack_id") == pack_id:
                _write_channel(base, channel, latest)
                return latest

    parent_pointer = _channel_pointer(base, channel)
    parent_version = int(parent_pointer["version"]) if parent_pointer else None
    parent_dir = base / f"v{parent_version}" if parent_version else None
    parent_inventory = _load_inventory(parent_dir) if parent_dir and parent_dir.is_dir() else []

    parent_sha = {entry["path"]: entry["sha256"] for entry in parent_inventory}
    child_sha = {entry["path"]: entry["sha256"] for entry in inventory}
    changes = {
        "added": sorted(set(child_sha) - set(parent_sha)),
        "updated": sorted(path for path in set(child_sha) & set(parent_sha) if child_sha[path] != parent_sha[path]),
        "removed": sorted(set(parent_sha) - set(child_sha)),
    }

    next_version = version if version is not None else (max(_versions(base), default=0) + 1)
    if version is not None and (base / f"v{next_version}").exists():
        raise PackError(f"pack version already exists: v{next_version}")

    state = {
        name: _sha256_text(_read_text(vault / name))
        for name in STATE_FILES
        if (vault / name).is_file()
    }
    manifest = {
        "pack_format": PACK_FORMAT,
        "pack_id": pack_id,
        "vault_id": identity,
        "version": next_version,
        "channel": channel,
        "created_at": _now(),
        "parent_pack_id": parent_pointer.get("pack_id") if parent_pointer else None,
        "source": {
            "vault_commit": commit,
            "dirty": dirty,
            "graph_wiki_version": __version__,
            "knowledge_pack": contracts["knowledge_pack"],
            "contracts": contracts,
        },
        "build": {
            "mode": "full",
            "deterministic": not dirty,
            "visibility_filter": sorted(filters),
        },
        "freshness": {
            "max_age_days": age,
            "policy_sha256": _sha256_bytes(_canonical_json(policy)),
            "built_at": _now(),
        },
        "state": state,
        "counts": _counts(inventory),
        "inventory_sha256": _sha256_text(_jsonl(inventory)),
        "edges_sha256": _sha256_text(_jsonl(edges)),
        "changes": changes,
    }

    temporary = Path(tempfile.mkdtemp(prefix=".pack-", dir=base))
    try:
        (temporary / "bodies").mkdir(parents=True, exist_ok=True)
        for sha, text in bodies.items():
            target = temporary / "bodies" / f"{sha.removeprefix('sha256:')}.md"
            if not target.exists():
                target.write_text(text, encoding="utf-8")
        (temporary / "inventory.jsonl").write_text(_jsonl(inventory), encoding="utf-8")
        (temporary / "edges.jsonl").write_text(_jsonl(edges), encoding="utf-8")
        _write_json(temporary / "manifest.json", manifest)
        target_dir = base / f"v{next_version}"
        if target_dir.exists():
            raise PackError(f"pack version already exists: v{next_version}")
        os.replace(temporary, target_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    _write_channel(base, channel, manifest)
    return manifest


def verify_pack(pack_dir: Path) -> dict[str, Any]:
    """Check pack identity, inventory, and body hashes without any engine."""
    pack_dir = Path(pack_dir)
    manifest = load_manifest(pack_dir)
    errors: list[str] = []
    warnings: list[str] = []

    inventory_path = pack_dir / "inventory.jsonl"
    edges_path = pack_dir / "edges.jsonl"
    if not inventory_path.is_file():
        raise PackError(f"pack inventory is missing: {inventory_path}")
    inventory_bytes = inventory_path.read_bytes()
    inventory = _load_inventory(pack_dir)
    edges_bytes = edges_path.read_bytes() if edges_path.is_file() else b""

    if manifest.get("inventory_sha256") != _sha256_bytes(inventory_bytes):
        errors.append("inventory_sha256 mismatch")
    if edges_path.is_file() and manifest.get("edges_sha256") != _sha256_bytes(edges_bytes):
        errors.append("edges_sha256 mismatch")
    if manifest.get("counts", {}).get("pages") != len(inventory):
        errors.append("page count does not match inventory")

    identity = _pack_identity(
        str(manifest.get("vault_id", "")),
        dict(manifest.get("source", {}).get("contracts", {})),
        list(manifest.get("build", {}).get("visibility_filter", [])),
        int(manifest.get("freshness", {}).get("max_age_days", 0)),
        inventory,
    )
    if _pack_id(identity) != manifest.get("pack_id"):
        errors.append("pack_id does not match content")

    for entry in inventory:
        sha = str(entry.get("sha256", ""))
        if not _SHA_RE.match(sha):
            errors.append(f"invalid sha256 for {entry.get('path')}")
            continue
        body = pack_dir / "bodies" / f"{sha.removeprefix('sha256:')}.md"
        if not body.is_file():
            errors.append(f"missing body for {entry.get('path')}")
            continue
        if hashlib.sha256(body.read_bytes()).hexdigest() != sha.removeprefix("sha256:"):
            errors.append(f"body hash mismatch for {entry.get('path')}")

    return {
        "ok": not errors,
        "pack_id": manifest.get("pack_id"),
        "version": manifest.get("version"),
        "vault_id": manifest.get("vault_id"),
        "errors": errors,
        "warnings": warnings,
        "counts": manifest.get("counts", {}),
    }


def diff_packs(before: Path, after: Path) -> dict[str, Any]:
    """Compare two packs by page content hash."""
    before = Path(before)
    after = Path(after)
    old = {entry["path"]: entry for entry in _load_inventory(before)}
    new = {entry["path"]: entry for entry in _load_inventory(after)}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    updated = sorted(path for path in set(old) & set(new) if old[path]["sha256"] != new[path]["sha256"])
    return {
        "before": load_manifest(before)["pack_id"],
        "after": load_manifest(after)["pack_id"],
        "added": added,
        "updated": updated,
        "removed": removed,
        "counts": {"added": len(added), "updated": len(updated), "removed": len(removed)},
    }


def list_packs(store: Path | None = None, vault_id: str | None = None) -> list[dict[str, Any]]:
    if vault_id is None:
        raise PackError("vault_id is required")
    base = Path(store).expanduser().resolve() / vault_id if store else default_store() / vault_id
    manifests = []
    for version in _versions(base):
        try:
            manifest = load_manifest(base / f"v{version}")
        except PackError:
            continue
        manifests.append(
            {
                "version": manifest["version"],
                "pack_id": manifest["pack_id"],
                "created_at": manifest.get("created_at"),
                "counts": manifest.get("counts", {}),
                "parent_pack_id": manifest.get("parent_pack_id"),
            }
        )
    return manifests


def resolve_pack(
    selector: str | Path | None = None,
    *,
    store: Path | None = None,
    vault_id: str | None = None,
    vault: Path | None = None,
    channel: str = DEFAULT_CHANNEL,
) -> Path:
    """Resolve a pack path from an explicit directory, version, channel, or id."""
    if selector is not None and not isinstance(selector, (str, Path)):
        raise PackError("pack selector must be a path or string")
    if isinstance(selector, Path) or (isinstance(selector, str) and Path(selector).expanduser().is_dir()):
        candidate = Path(selector).expanduser().resolve()
        if (candidate / "manifest.json").is_file():
            return candidate
    if vault_id is None:
        if vault is None:
            raise PackError("vault or vault_id is required to resolve a pack")
        vault = Path(vault).expanduser().resolve()
        vault_id = vault_identity(vault, load_policy(vault))
    if store is None:
        store = default_store()
    base = Path(store).expanduser().resolve() / vault_id
    text = str(selector).strip() if selector is not None else ""
    if text:
        if text.startswith("v") and text[1:].isdigit():
            text = text[1:]
        if text.isdigit():
            target = base / f"v{int(text)}"
            if (target / "manifest.json").is_file():
                return target
            raise PackError(f"pack version not found: v{text}")
        if text.startswith("sha256:"):
            for candidate in sorted(base.glob("v*")):
                if (candidate / "manifest.json").is_file() and load_manifest(candidate)["pack_id"] == text:
                    return candidate
            raise PackError(f"pack id not found: {text}")
        pointer = _channel_pointer(base, text)
        if pointer:
            target = base / f"v{int(pointer['version'])}"
            if (target / "manifest.json").is_file():
                return target
        raise PackError(f"pack channel not found: {text}")
    pointer = _channel_pointer(base, channel)
    if pointer:
        target = base / f"v{int(pointer['version'])}"
        if (target / "manifest.json").is_file():
            return target
    versions = _versions(base)
    if versions:
        return base / f"v{versions[-1]}"
    raise PackError(f"no packs found for vault: {vault_id}")


def status(
    vault: Path,
    *,
    store: Path | None = None,
    channel: str = DEFAULT_CHANNEL,
    pinned: str | None = None,
) -> dict[str, Any]:
    """Report the channel pack, latest pack, and live-vault drift."""
    vault = Path(vault).expanduser().resolve()
    policy = load_policy(vault)
    identity = vault_identity(vault, policy)
    base = (Path(store).expanduser().resolve() if store else default_store()) / identity
    current = resolve_pack(None, store=store, vault_id=identity, channel=channel)
    current_manifest = load_manifest(current)
    latest_version = max(_versions(base), default=current_manifest["version"])
    pinned_dir = resolve_pack(pinned, store=store, vault_id=identity) if pinned else None

    changed: list[str] = []
    missing: list[str] = []
    for entry in _load_inventory(current):
        path = vault / entry["path"]
        if not path.is_file():
            missing.append(entry["path"])
            continue
        if _sha256_text(_read_text(path)) != entry["sha256"]:
            changed.append(entry["path"])

    return {
        "vault_id": identity,
        "channel": channel,
        "version": current_manifest["version"],
        "pack_id": current_manifest["pack_id"],
        "latest_version": latest_version,
        "pinned_version": load_manifest(pinned_dir)["version"] if pinned_dir else None,
        "drift": {"changed": changed, "missing": missing},
        "counts": current_manifest.get("counts", {}),
    }


def materialize(pack_dir: Path, destination: Path, *, force: bool = False) -> dict[str, Any]:
    """Write a read-only page tree for grep-style agentic search."""
    pack_dir = Path(pack_dir)
    manifest = load_manifest(pack_dir)
    destination = Path(destination).expanduser().resolve()
    inventory = _load_inventory(pack_dir)
    if destination.exists() and not destination.is_dir():
        raise PackError(f"destination is not a directory: {destination}")
    if destination.exists() and any(destination.iterdir()) and not force:
        raise PackError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for entry in inventory:
        source = pack_dir / "bodies" / f"{entry['sha256'].removeprefix('sha256:')}.md"
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            continue
        if target.exists():
            target.unlink()
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        if os.name != "nt":
            try:
                os.chmod(target, 0o444)
            except OSError:
                pass
    _write_json(
        destination / ".pack.json",
        {
            "pack_id": manifest["pack_id"],
            "version": manifest["version"],
            "vault_id": manifest["vault_id"],
            "built_at": manifest.get("freshness", {}).get("built_at"),
        },
    )
    return {"destination": str(destination), "pages": len(inventory), "pack_id": manifest["pack_id"]}
