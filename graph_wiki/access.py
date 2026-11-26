"""Role-scoped content packs and a token-gated retrieval gateway.

Graph Wiki's vault is a single writable source of truth, but different audiences
must not receive the same documents. This module implements the "physical
isolation" model: every role gets its own immutable Content Pack built from the
pages that role may read. A principal may hold several roles, in which case the
gateway opens every role pack that principal holds and merges the results, so the
agent can explore its whole authorized corpus instead of a single pack.

Two files keep the model explicit:

* ``<vault>/_meta/access-policy.json`` — the content contract. Declares roles and
  which sensitivity tags each role must not receive. Pages tagged ``role/<name>``
  are delivered only to that role; untagged pages are shared.
* ``<config-dir>/access/principals.json`` — the identity contract. Maps named
  principals to roles and stores only token hashes, never plaintext tokens.

The gateway never falls back to the live vault: a missing, stale, or tampered
role pack is an error, not a degraded answer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from graph_wiki import config_paths
from graph_wiki.index import build_page_index
from graph_wiki import pack as pack_mod

POLICY_PATH = Path("_meta") / "access-policy.json"
ROLE_TAG_PREFIX = "role/"
ROLE_CHANNEL_PREFIX = "role-"
SIDECAR_NAME = "access.json"
TOKEN_PREFIX = "gw_"
TOKEN_ENV = "GRAPH_WIKI_ACCESS_TOKEN"
ACCESS_SEMANTICS = 1
DEFAULT_EXCLUDES = ("visibility/pii",)

_ROLE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TOKEN_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_POLICY_KEYS = {"version", "description", "default_exclude_tags", "roles"}
_ROLE_KEYS = {"description", "exclude_tags"}
_SIDECAR_KEYS = {
    "version",
    "role",
    "channel",
    "policy_sha256",
    "allowed_sha256",
    "visible_pages",
    "excluded_pages",
    "pack_id",
    "pack_version",
    "built_at",
}


class AccessError(RuntimeError):
    """An access decision, role pack, or principal record was invalid."""

    def __init__(self, message: str, *, reason: str = "access_denied") -> None:
        super().__init__(message)
        self.reason = reason


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str, *, mode: int) -> None:
    created = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if created:
        try:
            os.chmod(path.parent, 0o700 if mode == 0o600 else 0o755)
        except OSError:
            pass
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def config_dir() -> Path:
    """Return the resolved configuration directory that holds access state."""
    return config_paths.resolve_config_dir(default=Path.home() / ".graph-wiki")


def principals_file() -> Path:
    return config_dir() / "access" / "principals.json"


def audit_file() -> Path:
    return config_dir() / "audit" / "access.jsonl"


def role_channel(role: str) -> str:
    """Return the pack channel owned by one role."""
    return ROLE_CHANNEL_PREFIX + role


def role_tag(role: str) -> str:
    return ROLE_TAG_PREFIX + role


def _require_role(role: str) -> str:
    value = str(role or "").strip()
    if not _ROLE_RE.match(value):
        raise AccessError(
            "invalid role name: use lowercase letters, digits, '.', '_' or '-'",
            reason="invalid_policy",
        )
    return value


def _require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AccessError(f"{field} must be a string array", reason="invalid_policy")
    cleaned: list[str] = []
    for item in value:
        text = item.strip()
        if not text:
            raise AccessError(f"{field} entries must be non-empty", reason="invalid_policy")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def validate_policy(raw: Any) -> dict[str, Any]:
    """Validate an access policy and return a normalized copy (fail closed)."""
    if not isinstance(raw, dict):
        raise AccessError("access policy must be a JSON object", reason="invalid_policy")
    unknown = set(raw) - _POLICY_KEYS
    if unknown:
        raise AccessError(f"unknown access policy keys: {sorted(unknown)}", reason="invalid_policy")
    if raw.get("version") != 1:
        raise AccessError("access policy version must be 1", reason="invalid_policy")
    defaults = _require_string_list(raw.get("default_exclude_tags", list(DEFAULT_EXCLUDES)), "default_exclude_tags")
    roles = raw.get("roles", {})
    if not isinstance(roles, dict):
        raise AccessError("access policy roles must be a mapping", reason="invalid_policy")
    normalized: dict[str, dict[str, Any]] = {}
    for name, config in roles.items():
        role = _require_role(name)
        if not isinstance(config, dict):
            raise AccessError(f"role {role} must be a mapping", reason="invalid_policy")
        role_unknown = set(config) - _ROLE_KEYS
        if role_unknown:
            raise AccessError(f"unknown keys for role {role}: {sorted(role_unknown)}", reason="invalid_policy")
        description = config.get("description", "")
        if not isinstance(description, str):
            raise AccessError(f"description for role {role} must be a string", reason="invalid_policy")
        excludes = _require_string_list(config.get("exclude_tags", defaults), f"role {role} exclude_tags")
        normalized[role] = {"description": description.strip(), "exclude_tags": excludes}
    return {
        "version": 1,
        "description": str(raw.get("description", "")).strip(),
        "default_exclude_tags": defaults,
        "roles": normalized,
    }


def policy_path(vault: Path) -> Path:
    return Path(vault) / POLICY_PATH


def load_policy(vault: Path) -> dict[str, Any]:
    """Read and validate ``_meta/access-policy.json``."""
    path = policy_path(vault)
    if not path.is_file():
        raise AccessError(
            f"access policy not found: {path}; run `graph-wiki access init`",
            reason="policy_missing",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AccessError(f"invalid access policy: {path}: {exc}", reason="invalid_policy") from exc
    return validate_policy(raw)


def default_policy(roles: Iterable[str]) -> dict[str, Any]:
    """Return a starter policy: declared roles hide PII and keep team-internal pages."""
    normalized = {}
    for role in roles:
        name = _require_role(role)
        normalized[name] = {"description": "", "exclude_tags": list(DEFAULT_EXCLUDES)}
    return {
        "version": 1,
        "description": "",
        "default_exclude_tags": list(DEFAULT_EXCLUDES),
        "roles": normalized,
    }


def write_policy(vault: Path, policy: dict[str, Any], *, force: bool = False) -> Path:
    path = policy_path(vault)
    if path.exists() and not force:
        raise AccessError(
            f"access policy already exists: {path}; pass --force to replace it",
            reason="policy_exists",
        )
    normalized = validate_policy(policy)
    _atomic_write(path, json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", mode=0o644)
    return path


def role_config(policy: dict[str, Any], role: str) -> dict[str, Any]:
    config = policy["roles"].get(role)
    if config is None:
        raise AccessError(f"role not configured in access policy: {role}", reason="unknown_role")
    return {
        "role": role,
        "channel": role_channel(role),
        "exclude_tags": list(config["exclude_tags"]),
        "description": config["description"],
    }


def page_visible(tags: Iterable[str], role: str, exclude_tags: Iterable[str]) -> bool:
    """Decide whether one page belongs in a role's pack."""
    tag_list = [str(tag) for tag in tags]
    role_tags = [tag for tag in tag_list if tag.startswith(ROLE_TAG_PREFIX)]
    if role_tags and role_tag(role) not in role_tags:
        return False
    blocked = set(exclude_tags)
    return not any(tag in blocked for tag in tag_list)


def policy_fingerprint(policy: dict[str, Any], role: str) -> str:
    config = role_config(policy, role)
    return _sha256_text(
        json.dumps(
            {
                "semantics": ACCESS_SEMANTICS,
                "role": role,
                "channel": config["channel"],
                "exclude_tags": sorted(config["exclude_tags"]),
                "default_exclude_tags": sorted(policy["default_exclude_tags"]),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _allowed_fingerprint(pages: dict[str, dict[str, Any]], allowed: Iterable[str]) -> str:
    rows = [
        [relative, int(pages[relative].get("mtime_ns", 0)), int(pages[relative].get("size", 0))]
        for relative in sorted(allowed)
    ]
    return _sha256_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))


def role_snapshot(vault: Path, policy: dict[str, Any], role: str) -> dict[str, Any]:
    """Compute the pages a role may read, from the live vault."""
    config = role_config(policy, role)
    pages = build_page_index(Path(vault))
    allowed = [
        relative
        for relative, entry in pages.items()
        if page_visible(entry.get("tags", []), role, config["exclude_tags"])
    ]
    known = set(policy["roles"])
    unknown_tags = sorted(
        {
            tag
            for entry in pages.values()
            for tag in entry.get("tags", [])
            if str(tag).startswith(ROLE_TAG_PREFIX) and str(tag)[len(ROLE_TAG_PREFIX):] not in known
        }
    )
    return {
        "role": role,
        "channel": config["channel"],
        "exclude_tags": config["exclude_tags"],
        "allowed": allowed,
        "visible_pages": len(allowed),
        "excluded_pages": len(pages) - len(allowed),
        "total_pages": len(pages),
        "allowed_sha256": _allowed_fingerprint(pages, allowed),
        "policy_sha256": policy_fingerprint(policy, role),
        "unknown_role_tags": unknown_tags,
    }


def sidecar_path(pack_dir: Path) -> Path:
    return Path(pack_dir) / SIDECAR_NAME


def read_sidecar(pack_dir: Path) -> dict[str, Any]:
    path = sidecar_path(pack_dir)
    if not path.is_file():
        raise AccessError(
            f"role pack has no access sidecar: {path}; rebuild it with `graph-wiki access build`",
            reason="sidecar_missing",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AccessError(f"invalid access sidecar: {path}: {exc}", reason="sidecar_invalid") from exc
    if not isinstance(raw, dict) or set(raw) - _SIDECAR_KEYS:
        raise AccessError(f"invalid access sidecar: {path}", reason="sidecar_invalid")
    return raw


def _write_sidecar(pack_dir: Path, record: dict[str, Any]) -> Path:
    path = sidecar_path(pack_dir)
    _atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n", mode=0o444)
    return path


def build_role_pack(
    vault: Path,
    role: str,
    *,
    store: Path | None = None,
    index: str = "sqlite",
    allow_dirty: bool = False,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """Build one immutable Content Pack containing only what ``role`` may read."""
    vault = Path(vault).expanduser().resolve()
    policy = load_policy(vault)
    role = _require_role(role)
    snapshot = role_snapshot(vault, policy, role)
    extra = {
        "access_semantics": ACCESS_SEMANTICS,
        "access_role": role,
        "access_policy_sha256": snapshot["policy_sha256"],
        "access_visible_pages": snapshot["visible_pages"],
        "access_excluded_pages": snapshot["excluded_pages"],
    }
    try:
        manifest = pack_mod.build_pack(
            vault,
            store=store,
            channel=snapshot["channel"],
            allow_dirty=allow_dirty,
            max_age_days=max_age_days,
            include_paths=snapshot["allowed"],
            build_extra=extra,
        )
        pack_dir = pack_mod.resolve_pack(None, store=store, vault=vault, channel=snapshot["channel"])
    except pack_mod.PackError as exc:
        raise AccessError(str(exc), reason="build_failed") from exc

    indexes: dict[str, Any] = {}
    warnings: list[str] = []
    if index != "none":
        from graph_wiki import pack_index

        requested = ["sqlite"] if index == "all" else [index]
        if index == "all":
            requested = ["sqlite", "sqlite-simple", "zvec"]
        for engine in requested:
            try:
                indexes[engine] = pack_index.build_index(pack_dir, engine)
            except pack_index.PackIndexError as exc:
                if index == "all":
                    warnings.append(f"{engine}: {exc}")
                else:
                    raise AccessError(str(exc), reason="index_failed") from exc

    record = {
        "version": 1,
        "role": role,
        "channel": snapshot["channel"],
        "policy_sha256": snapshot["policy_sha256"],
        "allowed_sha256": snapshot["allowed_sha256"],
        "visible_pages": snapshot["visible_pages"],
        "excluded_pages": snapshot["excluded_pages"],
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["version"],
        "built_at": _now(),
    }
    sidecar = _write_sidecar(pack_dir, record)
    return {
        "role": role,
        "channel": snapshot["channel"],
        "pack_id": manifest["pack_id"],
        "version": manifest["version"],
        "pack_dir": str(pack_dir),
        "sidecar": str(sidecar),
        "visible_pages": snapshot["visible_pages"],
        "excluded_pages": snapshot["excluded_pages"],
        "unknown_role_tags": snapshot["unknown_role_tags"],
        "indexes": indexes,
        "warnings": warnings,
    }


def _verify_role_pack(
    vault: Path,
    role: str,
    *,
    store: Path | None,
    skip_drift: bool,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    policy = load_policy(vault)
    role = _require_role(role)
    config = role_config(policy, role)
    try:
        pack_dir = pack_mod.resolve_pack(None, store=store, vault=vault, channel=config["channel"])
    except pack_mod.PackError as exc:
        raise AccessError(
            f"no pack for role {role}; run `graph-wiki access build --role {role}`",
            reason="pack_missing",
        ) from exc
    manifest = pack_mod.load_manifest(pack_dir)
    sidecar = read_sidecar(pack_dir)
    if sidecar.get("role") != role:
        raise AccessError("access sidecar does not belong to this role", reason="sidecar_mismatch")
    if sidecar.get("pack_id") != manifest.get("pack_id"):
        raise AccessError("access sidecar does not match the pack; rebuild it", reason="sidecar_mismatch")
    if sidecar.get("policy_sha256") != policy_fingerprint(policy, role):
        raise AccessError(
            f"access policy changed since the {role} pack was built; run `graph-wiki access build --role {role}`",
            reason="policy_drift",
        )
    snapshot = None
    if not skip_drift:
        snapshot = role_snapshot(vault, policy, role)
        if sidecar.get("allowed_sha256") != snapshot["allowed_sha256"]:
            raise AccessError(
                f"vault content for role {role} changed since its pack was built; "
                f"run `graph-wiki access build --role {role}`",
                reason="content_drift",
            )
    return pack_dir, manifest, sidecar, snapshot


def verify_role_pack(
    vault: Path,
    role: str,
    *,
    store: Path | None = None,
    skip_drift: bool = False,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Resolve a role pack and prove it still matches the current policy and vault."""
    resolved = Path(vault).expanduser().resolve()
    return _verify_role_pack(resolved, role, store=store, skip_drift=skip_drift)


def verify_principal_packs(
    vault: Path,
    roles: Iterable[str],
    *,
    store: Path | None = None,
    skip_drift: bool = False,
) -> tuple[Path, list[dict[str, Any]]]:
    """Verify every role pack a principal may use; deny the query if any one is stale."""
    resolved = Path(vault).expanduser().resolve()
    role_list = _role_list(roles)
    policy = load_policy(resolved)
    packs: list[dict[str, Any]] = []
    for role in role_list:
        role_config(policy, role)
        pack_dir, manifest, sidecar, snapshot = _verify_role_pack(
            resolved, role, store=store, skip_drift=skip_drift
        )
        inventory = pack_mod.load_inventory(pack_dir)
        raw_allowed = snapshot["allowed"] if snapshot else [row["path"] for row in inventory]
        allowed = {_normalise_page_path(path) for path in raw_allowed}
        packs.append(
            {
                "role": role,
                "pack_dir": pack_dir,
                "manifest": manifest,
                "sidecar": sidecar,
                "snapshot": snapshot,
                "inventory": inventory,
                "allowed": allowed,
            }
        )
    return resolved, packs


def policy_roles(policy: dict[str, Any]) -> list[str]:
    return sorted(policy["roles"])


def _load_principal_document() -> dict[str, Any]:
    path = principals_file()
    if not path.is_file():
        return {"version": 1, "principals": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AccessError(f"invalid principals file: {path}: {exc}", reason="invalid_principals") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise AccessError(f"invalid principals file: {path}", reason="invalid_principals")
    principals = raw.get("principals", {})
    if not isinstance(principals, dict):
        raise AccessError(f"invalid principals file: {path}", reason="invalid_principals")
    return {"version": 1, "principals": principals}


def _save_principal_document(document: dict[str, Any]) -> None:
    _atomic_write(
        principals_file(),
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )


def _role_list(roles: str | Iterable[str]) -> list[str]:
    raw = [roles] if isinstance(roles, str) else list(roles)
    cleaned: list[str] = []
    for role in raw:
        name = _require_role(role)
        if name not in cleaned:
            cleaned.append(name)
    if not cleaned:
        raise AccessError("at least one role is required", reason="invalid_principal")
    return sorted(cleaned)


def _record_roles(record: dict[str, Any]) -> list[str]:
    stored = record.get("roles")
    if isinstance(stored, list) and stored:
        try:
            return _role_list(stored)
        except AccessError:
            return []
    legacy = record.get("role")
    if isinstance(legacy, str) and legacy:
        try:
            return [_require_role(legacy)]
        except AccessError:
            return []
    return []


def create_token(
    name: str,
    roles: str | Iterable[str],
    *,
    vault_id: str | None = None,
    replace: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Create a principal holding one or more roles and return its token exactly once."""
    principal = str(name or "").strip()
    if not _ROLE_RE.match(principal):
        raise AccessError(
            "invalid principal name: use lowercase letters, digits, '.', '_' or '-'",
            reason="invalid_principal",
        )
    role_list = _role_list(roles)
    document = _load_principal_document()
    if principal in document["principals"] and not replace:
        raise AccessError(
            f"principal already exists: {principal}; revoke it first or pass --replace",
            reason="principal_exists",
        )
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    record = {
        "roles": role_list,
        "token_sha256": _sha256_text(token),
        "created_at": _now(),
        "revoked_at": None,
        "vault_id": (vault_id or "").strip() or None,
    }
    document["principals"][principal] = record
    _save_principal_document(document)
    return token, {"name": principal, **record}


def revoke_token(name: str) -> dict[str, Any]:
    document = _load_principal_document()
    record = document["principals"].get(name)
    if record is None:
        raise AccessError(f"unknown principal: {name}", reason="unknown_principal")
    if not record.get("revoked_at"):
        record["revoked_at"] = _now()
        _save_principal_document(document)
    return {"name": name, "roles": _record_roles(record), **record}


def list_principals() -> list[dict[str, Any]]:
    document = _load_principal_document()
    return [
        {
            "name": name,
            "roles": _record_roles(record),
            "created_at": record.get("created_at"),
            "revoked_at": record.get("revoked_at"),
            "vault_id": record.get("vault_id"),
        }
        for name, record in sorted(document["principals"].items())
    ]


def resolve_principal(token: str, *, vault_id: str | None = None) -> dict[str, Any]:
    """Resolve a bearer token to a principal without leaking which part failed."""
    value = str(token or "")
    if not value:
        raise AccessError("access denied: missing token", reason="missing_token")
    digest = _sha256_text(value)
    document = _load_principal_document()
    matched: tuple[str, dict[str, Any]] | None = None
    for name, record in document["principals"].items():
        stored = str(record.get("token_sha256", ""))
        if not _TOKEN_HASH_RE.match(stored):
            continue
        if hmac.compare_digest(stored, digest) and not record.get("revoked_at"):
            matched = (name, record)
    if matched is None:
        raise AccessError("access denied: invalid token", reason="invalid_token")
    name, record = matched
    roles = _record_roles(record)
    if not roles:
        raise AccessError("access denied: token has no valid roles", reason="no_roles")
    pinned = str(record.get("vault_id") or "")
    if pinned and vault_id and pinned != vault_id:
        raise AccessError("access denied: token is scoped to another vault", reason="vault_mismatch")
    return {"name": name, "roles": roles, "vault_id": pinned or vault_id}


def _audit_decision(
    action: str,
    token: str,
    outcome: str,
    *,
    reason: str | None = None,
    principal: str | None = None,
    roles: Iterable[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    row: dict[str, Any] = {
        "ts": _now(),
        "action": action,
        "outcome": outcome,
        "token_sha256_prefix": _sha256_text(str(token or ""))[:19],
    }
    if reason:
        row["reason"] = reason
    if principal:
        row["principal"] = principal
    if roles:
        row["roles"] = list(roles)
    if extra:
        row.update(extra)
    _append_audit(row)


def _append_audit(record: dict[str, Any]) -> None:
    path = audit_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        if not path.exists():
            path.touch(mode=0o600)
        else:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # Auditing must never turn a successful, already-filtered read into a leak.
        pass


def read_audit(limit: int = 50) -> list[dict[str, Any]]:
    path = audit_file()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[-max(1, limit):]


def pack_vault_id(vault: Path) -> str:
    """Return the pack-store identity for a vault (shared with ``pack status``)."""
    resolved = Path(vault).expanduser().resolve()
    return pack_mod.vault_identity(resolved, pack_mod.load_policy(resolved))


RRF_K = 60


def _normalise_page_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.startswith("/"):
        raise AccessError("invalid page path", reason="invalid_page_path")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise AccessError("invalid page path", reason="invalid_page_path")
    return "/".join(parts)


def _granted_by(packs: Iterable[dict[str, Any]], path: str) -> list[str]:
    return sorted(pack["role"] for pack in packs if path in pack["allowed"])


def _pack_visible_total(packs: Iterable[dict[str, Any]]) -> int | None:
    totals = [pack["snapshot"]["total_pages"] for pack in packs if pack["snapshot"]]
    return max(totals) if totals else None


def _merge_role_results(
    packs: list[dict[str, Any]],
    per_pack: dict[str, dict[str, Any]],
    topk: int,
) -> list[dict[str, Any]]:
    """Fuse page hits from several role packs without trusting cross-pack scores.

    Each role pack is searched separately. Pages are deduplicated by path and
    ranked with reciprocal rank fusion, so a shared page returned by three roles
    appears once and the ordering does not depend on engine-local BM25 scales.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for pack in packs:
        role = pack["role"]
        for rank, item in enumerate(per_pack[role]["results"], start=1):
            path = _normalise_page_path(item.get("path", ""))
            bucket = buckets.setdefault(
                path,
                {"score": 0.0, "ranks": {}, "shas": set(), "best_rank": rank, "item": item},
            )
            bucket["score"] += 1.0 / (RRF_K + rank)
            bucket["ranks"][role] = rank
            sha = str(item.get("sha256", ""))
            if sha:
                bucket["shas"].add(sha)
            if rank < bucket["best_rank"]:
                bucket["best_rank"] = rank
                bucket["item"] = item

    rows: list[dict[str, Any]] = []
    for path, bucket in sorted(buckets.items(), key=lambda item: (-item[1]["score"], item[0]))[: max(0, topk)]:
        item = dict(bucket["item"])
        item["path"] = path
        item["engine_score"] = item.pop("score", None)
        item["score"] = round(bucket["score"], 6)
        item["ranks"] = dict(sorted(bucket["ranks"].items()))
        item["via_roles"] = sorted(bucket["ranks"])
        item["granted_by"] = _granted_by(packs, path)
        if len(bucket["shas"]) > 1:
            item["content_conflict"] = True
        rows.append(item)
    return rows


def gateway_search(
    token: str,
    query: str,
    *,
    vault: Path,
    store: Path | None = None,
    engine: str | None = None,
    topk: int = 10,
    operator: str = "AND",
    skip_drift: bool = False,
    role: str | None = None,
) -> dict[str, Any]:
    """Search every pack granted to the token's roles and fuse the results."""
    from graph_wiki import pack_index

    try:
        resolved = Path(vault).expanduser().resolve()
        identity = pack_vault_id(resolved)
        principal = resolve_principal(token, vault_id=identity)
        roles = list(principal["roles"])
        if role is not None:
            requested = _require_role(role)
            if requested not in roles:
                raise AccessError(
                    "access denied: role is not granted to this token", reason="role_not_granted"
                )
            roles = [requested]
        _resolved, packs = verify_principal_packs(
            resolved, roles, store=store, skip_drift=skip_drift
        )
        per_pack = {
            pack["role"]: pack_index.search_index(
                pack["pack_dir"],
                query,
                engine=engine,
                topk=max(topk, 10),
                operator=operator,
            )
            for pack in packs
        }
        merged = _merge_role_results(packs, per_pack, topk)
        union_allowed = set().union(*(pack["allowed"] for pack in packs))
        total_pages = _pack_visible_total(packs)
    except (AccessError, pack_mod.PackError, pack_index.PackIndexError) as exc:
        reason = getattr(exc, "reason", "error")
        _audit_decision(
            "search",
            token,
            "denied" if isinstance(exc, AccessError) else "error",
            reason=reason,
            extra={"query": str(query or "")[:500]},
        )
        if isinstance(exc, AccessError):
            raise
        raise AccessError(str(exc), reason=reason) from exc

    returned = [str(item["path"]) for item in merged]
    _audit_decision(
        "search",
        token,
        "ok",
        principal=principal["name"],
        roles=roles,
        extra={
            "packs": [pack["manifest"]["pack_id"] for pack in packs],
            "query": str(query or "")[:500],
            "returned": returned,
            "count": len(returned),
            "drift_checked": not skip_drift,
        },
    )
    return {
        "schema_version": 1,
        "principal": principal["name"],
        "roles": roles,
        "vault_id": identity,
        "packs": [
            {
                "role": pack["role"],
                "channel": pack["sidecar"]["channel"],
                "pack_id": pack["manifest"]["pack_id"],
                "pack_version": pack["manifest"]["version"],
                "visible_pages": len(pack["allowed"]),
            }
            for pack in packs
        ],
        "content_trust": "untrusted_reference_data",
        "coverage": {
            "roles": len(packs),
            "visible_pages": len(union_allowed),
            "excluded_pages": (total_pages - len(union_allowed)) if total_pages is not None else None,
            "drift_checked": not skip_drift,
        },
        "query": query,
        "count": len(merged),
        "results": merged,
    }


def gateway_inventory(
    token: str,
    *,
    vault: Path,
    store: Path | None = None,
    skip_drift: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """List every page the token's roles can read, deduplicated by path."""
    try:
        resolved = Path(vault).expanduser().resolve()
        identity = pack_vault_id(resolved)
        principal = resolve_principal(token, vault_id=identity)
        _resolved, packs = verify_principal_packs(
            resolved, principal["roles"], store=store, skip_drift=skip_drift
        )
    except AccessError as exc:
        _audit_decision("inventory", token, "denied", reason=exc.reason)
        raise
    except pack_mod.PackError as exc:
        _audit_decision("inventory", token, "error", reason="error")
        raise AccessError(str(exc), reason="error") from exc

    union: dict[str, dict[str, Any]] = {}
    for pack in packs:
        for entry in pack["inventory"]:
            path = _normalise_page_path(entry.get("path", ""))
            bucket = union.setdefault(path, {"entry": entry, "roles": set()})
            bucket["roles"].add(pack["role"])
    rows = [
        {
            "path": path,
            "title": union[path]["entry"].get("title", ""),
            "summary": union[path]["entry"].get("summary", ""),
            "tags": union[path]["entry"].get("tags", []),
            "lifecycle": union[path]["entry"].get("lifecycle", ""),
            "updated": union[path]["entry"].get("updated", ""),
            "stale_after": union[path]["entry"].get("stale_after", ""),
            "granted_by": sorted(union[path]["roles"]),
        }
        for path in sorted(union)
    ]
    selected = rows[max(0, offset) : max(0, offset) + max(0, limit)]
    _audit_decision(
        "inventory",
        token,
        "ok",
        principal=principal["name"],
        roles=principal["roles"],
        extra={"count": len(selected), "total": len(rows), "offset": offset},
    )
    return {
        "schema_version": 1,
        "principal": principal["name"],
        "roles": principal["roles"],
        "vault_id": identity,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "pages": selected,
    }


def gateway_page(
    token: str,
    page_path: str,
    *,
    vault: Path,
    store: Path | None = None,
    skip_drift: bool = False,
) -> dict[str, Any]:
    """Read one page from the role packs, refusing anything outside them."""
    normalised = _normalise_page_path(page_path)
    try:
        resolved = Path(vault).expanduser().resolve()
        identity = pack_vault_id(resolved)
        principal = resolve_principal(token, vault_id=identity)
        _resolved, packs = verify_principal_packs(
            resolved, principal["roles"], store=store, skip_drift=skip_drift
        )
    except AccessError as exc:
        _audit_decision("page", token, "denied", reason=exc.reason, extra={"path": normalised})
        raise
    except pack_mod.PackError as exc:
        _audit_decision("page", token, "error", reason="error", extra={"path": normalised})
        raise AccessError(str(exc), reason="error") from exc

    for pack in packs:
        if normalised not in pack["allowed"]:
            continue
        entry = next(
            (row for row in pack["inventory"] if _normalise_page_path(row.get("path", "")) == normalised),
            None,
        )
        if entry is None:
            continue
        sha = str(entry.get("sha256", ""))
        body_path = pack["pack_dir"] / "bodies" / f"{sha.removeprefix('sha256:')}.md"
        try:
            body = body_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AccessError(f"pack body is unreadable: {exc}", reason="pack_corrupt") from exc
        payload = {
            "schema_version": 1,
            "principal": principal["name"],
            "roles": principal["roles"],
            "vault_id": identity,
            "path": normalised,
            "granted_by": _granted_by(packs, normalised),
            "title": entry.get("title", ""),
            "sha256": sha,
            "content_trust": "untrusted_reference_data",
            "body": body,
        }
        _audit_decision(
            "page",
            token,
            "ok",
            principal=principal["name"],
            roles=principal["roles"],
            extra={"path": normalised, "returned": [normalised], "count": 1},
        )
        return payload

    _audit_decision(
        "page",
        token,
        "denied",
        reason="page_denied",
        principal=principal["name"],
        roles=principal["roles"],
        extra={"path": normalised},
    )
    raise AccessError("access denied: page is not in the token's role packs", reason="page_denied")


def role_status(vault: Path, *, store: Path | None = None) -> dict[str, Any]:
    """Report every configured role, its pack, and whether the pack is current."""
    vault = Path(vault).expanduser().resolve()
    policy = load_policy(vault)
    roles: list[dict[str, Any]] = []
    for role in policy_roles(policy):
        snapshot = role_snapshot(vault, policy, role)
        entry: dict[str, Any] = {
            "role": role,
            "channel": role_channel(role),
            "exclude_tags": policy["roles"][role]["exclude_tags"],
            "built": False,
            "visible_pages": snapshot["visible_pages"],
            "excluded_pages": snapshot["excluded_pages"],
            "unknown_role_tags": snapshot["unknown_role_tags"],
        }
        try:
            pack_dir = pack_mod.resolve_pack(None, store=store, vault=vault, channel=role_channel(role))
            manifest = pack_mod.load_manifest(pack_dir)
        except pack_mod.PackError as exc:
            entry["error"] = str(exc)
            roles.append(entry)
            continue
        entry.update({"built": True, "pack_id": manifest["pack_id"], "version": manifest["version"]})
        try:
            sidecar = read_sidecar(pack_dir)
        except AccessError as exc:
            entry["error"] = str(exc)
            entry.update({"policy_current": False, "content_current": False})
            roles.append(entry)
            continue
        entry.update(
            {
                "policy_current": sidecar.get("policy_sha256") == snapshot["policy_sha256"],
                "content_current": sidecar.get("allowed_sha256") == snapshot["allowed_sha256"],
            }
        )
        roles.append(entry)
    return {
        "vault_id": pack_vault_id(vault),
        "policy_sha256": policy_revision(policy),
        "roles": roles,
    }


def policy_revision(policy: dict[str, Any]) -> str:
    return _sha256_text(json.dumps(validate_policy(policy), ensure_ascii=False, sort_keys=True))
