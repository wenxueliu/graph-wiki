"""Operational metrics for a vault: page events, change history, and reports.

The operations layer is deliberately outside the vault.  Frontmatter remains
the only semantic source of truth; this module derives a page inventory, an
append-only change history, and an append-only view/retrieval event log under
``~/.graph-wiki/state/<vault-id>/ops``.  Reports are rebuilt from those files,
so nothing here writes knowledge pages.

Recording is off by default.  ``graph-wiki serve --ops`` enables the viewer
collector; ``GRAPH_WIKI_OPS=1`` enables retrieval instrumentation for the CLI
retrieval commands.  ``ops scan``, ``ops report``, ``ops record``, and
``ops ingest`` always run when invoked explicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from graph_wiki.page_set import page_files
from graph_wiki.quality import (
    REVIEW_SLA_DAYS,
    load_review_ledger,
    review_sla,
)
from graph_wiki.relationships import split_frontmatter

OPS_SCHEMA_VERSION = 1
EVENT_VIEW = "view"
EVENT_RETRIEVAL = "retrieval"
EVENT_TYPES = frozenset({EVENT_VIEW, EVENT_RETRIEVAL})
DEFAULT_DEDUPE_MINUTES = 30
DEFAULT_AGING_DAYS = 365
DEFAULT_TOP = 10
DEFAULT_DAYS = 30
MAX_EVENT_BYTES = 64 * 1024
MAX_EVENT_PAGE = 512
MAX_EVENT_SOURCE = 40
MAX_EVENT_CLIENT = 128
VIEWER_OPS_HEADER = "X-Viewer-Id"
OPS_TOKEN_HEADER = "X-Graph-Wiki-Ops-Token"
OPS_EVENT_PATH = "/api/ops/event"

_FRONT_TOP_RE = re.compile(r"^([A-Za-z_][\w-]*):(?:\s*(.*))?$")
_UPDATED_LINE_RE = re.compile(r"^updated:\s.*$", re.MULTILINE)
_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CLIENT_RE = re.compile(r"^[^\s\x00-\x1f]{1,%d}$" % MAX_EVENT_CLIENT)
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


class OpsError(RuntimeError):
    """Operational metrics could not be read or written."""


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _parse_iso(value: Any, *, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise OpsError(f"invalid timestamp: {value!r}") from exc
    elif default is not None:
        return default
    else:
        raise OpsError("timestamp is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_now_local().tzinfo)
    return parsed.astimezone()


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    match = _DATE_RE.match(value.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _normalise_text(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalise_block(text: str) -> str:
    lines = [line.rstrip() for line in _normalise_text(text).split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def vault_id(vault: str | Path) -> str:
    return hashlib.md5(
        str(Path(vault).expanduser().resolve()).encode("utf-8")
    ).hexdigest()[:8]


def state_base() -> Path:
    return Path.home() / ".graph-wiki" / "state"


class OpsPaths:
    """Resolved file locations for one vault's operations state."""

    __slots__ = (
        "base",
        "vault_id",
        "root",
        "ops",
        "inventory",
        "history",
        "events",
        "token",
        "meta",
    )

    def __init__(self, base: Path, identity: str, ops: Path) -> None:
        self.base = base
        self.vault_id = identity
        self.root = ops.parent
        self.ops = ops
        self.inventory = ops / "inventory.json"
        self.history = ops / "history.jsonl"
        self.events = ops / "events"
        self.token = ops / "token"
        self.meta = ops / "meta.json"

    def as_dict(self) -> dict[str, str]:
        return {
            "ops_dir": str(self.ops),
            "inventory": str(self.inventory),
            "history": str(self.history),
            "events": str(self.events),
            "token": str(self.token),
        }


def ops_paths(
    vault: str | Path,
    *,
    base: str | Path | None = None,
    ops_dir: str | Path | None = None,
) -> OpsPaths:
    """Resolve the operations directory and reject one inside the vault."""
    resolved_vault = Path(vault).expanduser().resolve()
    if ops_dir is not None:
        ops = Path(ops_dir).expanduser().resolve()
        resolved_base = ops.parent.parent
    else:
        resolved_base = (
            Path(base).expanduser().resolve() if base is not None else state_base()
        )
        ops = resolved_base / vault_id(resolved_vault) / "ops"
    if ops == resolved_vault or resolved_vault in ops.parents:
        raise OpsError("operations state must be stored outside the vault")
    return OpsPaths(resolved_base, vault_id(resolved_vault), ops)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    _ensure_dir(path.parent)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        os.chmod(temporary, mode)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ensure_meta(paths: OpsPaths, vault: str | Path) -> dict[str, Any]:
    existing = _load_json(paths.meta)
    if isinstance(existing, dict) and existing.get("schema_version") == OPS_SCHEMA_VERSION:
        return existing
    meta = {
        "schema_version": OPS_SCHEMA_VERSION,
        "vault_path": str(Path(vault).expanduser().resolve()),
        "vault_id": paths.vault_id,
        "created_at": _now_local().isoformat(timespec="seconds"),
    }
    _ensure_dir(paths.ops)
    _atomic_write_json(paths.meta, meta)
    return meta


def ensure_token(paths: OpsPaths) -> str:
    _ensure_dir(paths.ops)
    try:
        value = paths.token.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        return value
    value = secrets.token_urlsafe(24)
    _atomic_write(paths.token, value + "\n")
    return value


# -- event validation and storage ------------------------------------------------


def _normalize_page(value: Any) -> str:
    page = str(value or "").strip()
    if page.endswith(".md"):
        page = page[:-3]
    page = page.replace("\\", "/").lstrip("/")
    if not page or len(page) > MAX_EVENT_PAGE:
        raise OpsError("page id is required")
    if page.startswith("../") or "/../" in page or page == "..":
        raise OpsError("page id must be vault-relative")
    parts = page.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise OpsError("page id must be vault-relative")
    if any(ord(char) < 32 for char in page):
        raise OpsError("page id contains control characters")
    return page


def normalize_event(payload: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate one event payload and fill the derived fields."""
    if not isinstance(payload, Mapping):
        raise OpsError("event must be a JSON object")
    event = str(payload.get("event") or "").strip().lower()
    if event not in EVENT_TYPES:
        raise OpsError(f"unsupported event type: {event or '(missing)'}")
    page = _normalize_page(payload.get("page"))
    source = str(payload.get("source") or "").strip().lower()
    if not source or len(source) > MAX_EVENT_SOURCE or not _SOURCE_RE.match(source):
        raise OpsError("source must be a lowercase identifier")
    client = str(payload.get("client") or "").strip()
    if client and not _CLIENT_RE.match(client):
        raise OpsError("client id is invalid")
    stamp = _parse_iso(payload.get("ts"), default=now or _now_local())
    return {
        "v": OPS_SCHEMA_VERSION,
        "ts": stamp.isoformat(timespec="seconds"),
        "day": stamp.date().isoformat(),
        "event": event,
        "page": page,
        "source": source,
        "client": client,
    }


def record_events(
    vault: str | Path,
    events: Iterable[Mapping[str, Any]],
    *,
    ops_dir: str | Path | None = None,
    base: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and append events.  One JSON object per line, one file per day."""
    paths = ops_paths(vault, base=base, ops_dir=ops_dir)
    _ensure_dir(paths.events)
    ensure_meta(paths, vault)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in events:
        try:
            event = normalize_event(raw, now=now)
        except OpsError as exc:
            rejected.append({"error": str(exc), "event": dict(raw) if isinstance(raw, Mapping) else raw})
            continue
        target = paths.events / f"{event['day']}.jsonl"
        line = _json_line(event) + "\n"
        handle = os.open(
            target,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        try:
            os.write(handle, line.encode("utf-8"))
        finally:
            os.close(handle)
        accepted.append(event)
    return {"accepted": len(accepted), "rejected": len(rejected), "errors": rejected[:20], "ops_dir": str(paths.ops)}


def record_event(
    vault: str | Path,
    *,
    event: str,
    page: str,
    source: str,
    client: str = "",
    ts: str | datetime | None = None,
    ops_dir: str | Path | None = None,
    base: str | Path | None = None,
) -> dict[str, Any]:
    result = record_events(
        vault,
        [{"event": event, "page": page, "source": source, "client": client, "ts": ts}],
        ops_dir=ops_dir,
        base=base,
    )
    if result["accepted"] != 1:
        error = result["errors"][0]["error"] if result["errors"] else "event was rejected"
        raise OpsError(error)
    return result


# -- page parsing and change detection ------------------------------------------


def _scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _parse_tags(front: str) -> list[str]:
    inline = re.search(r"^tags:\s*\[(.*?)\]\s*$", front, re.MULTILINE)
    if inline:
        return [item.strip().strip("'\"") for item in inline.group(1).split(",") if item.strip()]
    block = _parse_block_values(front, "tags")
    return block


def _parse_block_values(front: str, key: str) -> list[str]:
    values: list[str] = []
    in_block = False
    for line in front.splitlines():
        if re.match(rf"^{re.escape(key)}:", line):
            in_block = True
            continue
        if in_block:
            if line.startswith((" ", "\t")):
                item = line.strip()
                if item.startswith("- "):
                    values.append(_scalar(item[2:]))
            elif line.strip():
                break
    return values


def _parse_sources(front: str) -> list[dict[str, str]]:
    inline = re.search(r"^sources:\s*\[(.*?)\]\s*$", front, re.MULTILINE)
    if inline:
        items = [item.strip() for item in inline.group(1).split(",") if item.strip()]
        return [
            {"source_id": _scalar(item), "revision": ""}
            for item in items
        ]
    sources: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_block = False
    for line in front.splitlines():
        if re.match(r"^sources:", line):
            in_block = True
            continue
        if not in_block:
            continue
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            item = line.strip()
            if item.startswith("- "):
                if current:
                    sources.append(current)
                current = {}
                item = item[2:].strip()
            if ":" in item and current is not None:
                key, raw = item.split(":", 1)
                current[key.strip()] = _scalar(raw)
            continue
        break
    if current:
        sources.append(current)
    return [
        {
            "source_id": entry.get("source_id", ""),
            "revision": entry.get("revision", ""),
        }
        for entry in sources
        if entry
    ]


def _parse_operational_state(front: str) -> str:
    in_block = False
    for line in front.splitlines():
        if re.match(r"^operational_status:", line):
            in_block = True
            continue
        if not in_block:
            continue
        if line.startswith((" ", "\t")):
            item = line.strip()
            if item.startswith("state:"):
                return _scalar(item.split(":", 1)[1]).lower()
        elif line.strip():
            break
    return ""


def _parse_confidence(raw: str) -> float | None:
    try:
        value = float(_scalar(raw))
    except ValueError:
        return None
    return value if 0.0 <= value <= 1.0 else None


def _page_meta(path: Path, vault: Path) -> dict[str, Any]:
    text = _normalise_text(path.read_text(encoding="utf-8", errors="replace"))
    front, body = split_frontmatter(text)
    values: dict[str, str] = {}
    for line in front.splitlines():
        match = _FRONT_TOP_RE.match(line)
        if match:
            values[match.group(1)] = _scalar(match.group(2) or "")
    front_normal = _normalise_block(front)
    body_normal = _normalise_block(body)
    content_front = _normalise_block(_UPDATED_LINE_RE.sub("", front))
    file_hash = _sha256(text)
    body_hash = _sha256(body_normal)
    metadata_hash = _sha256(content_front)
    content_hash = _sha256(content_front + "\0" + body_normal)
    return {
        "title": values.get("title", "") or path.stem,
        "category": values.get("category", ""),
        "tags": _parse_tags(front),
        "summary": values.get("summary", ""),
        "lifecycle": values.get("lifecycle", "").lower(),
        "operational_state": _parse_operational_state(front),
        "base_confidence": _parse_confidence(values.get("base_confidence", "")),
        "created": values.get("created", ""),
        "updated": values.get("updated", ""),
        "sources": _parse_sources(front),
        "file_hash": file_hash,
        "content_hash": content_hash,
        "body_hash": body_hash,
        "metadata_hash": metadata_hash,
        "mtime_ns": path.stat().st_mtime_ns,
        "size": path.stat().st_size,
    }


def _static_warnings(meta: Mapping[str, Any], today: date) -> list[str]:
    warnings: list[str] = []
    created = _parse_date(meta.get("created"))
    updated = _parse_date(meta.get("updated"))
    if not str(meta.get("updated") or "").strip():
        warnings.append("updated_missing")
    elif updated is None:
        warnings.append("updated_invalid")
    elif updated > today + timedelta(days=1):
        warnings.append("updated_future")
    if str(meta.get("created") or "").strip() and created is None:
        warnings.append("created_invalid")
    if created and updated and created > updated:
        warnings.append("created_after_updated")
    return warnings


def _change_fields(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    changes: list[str] = []
    if previous.get("body_hash") != current.get("body_hash"):
        changes.append("body")
    for field in (
        "title",
        "category",
        "tags",
        "summary",
        "lifecycle",
        "operational_state",
        "base_confidence",
        "sources",
    ):
        if previous.get(field) != current.get(field):
            changes.append(field)
    if previous.get("updated") != current.get("updated") and not changes:
        changes.append("updated")
    return changes


def due_aging_days(config: Mapping[str, str] | None = None) -> int:
    raw = os.environ.get("GRAPH_WIKI_OPS_AGING_DAYS", "")
    if not raw and config:
        raw = config.get("GRAPH_WIKI_OPS_AGING_DAYS", "")
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_AGING_DAYS
    return value if value > 0 else DEFAULT_AGING_DAYS


def ops_enabled(config: Mapping[str, str] | None = None) -> bool:
    raw = os.environ.get("GRAPH_WIKI_OPS", "")
    if not raw and config:
        raw = config.get("GRAPH_WIKI_OPS", "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _inventory_entry(
    meta: Mapping[str, Any],
    *,
    version: int,
    first_seen: str,
    last_changed: str | None,
    last_changed_basis: str,
    warnings: list[str],
    baseline: bool = False,
) -> dict[str, Any]:
    return {
        "title": meta.get("title", ""),
        "category": meta.get("category", ""),
        "tags": list(meta.get("tags", [])),
        "summary": meta.get("summary", ""),
        "lifecycle": meta.get("lifecycle", ""),
        "operational_state": meta.get("operational_state", ""),
        "base_confidence": meta.get("base_confidence"),
        "created": meta.get("created", ""),
        "updated": meta.get("updated", ""),
        "sources": list(meta.get("sources", [])),
        "file_hash": meta.get("file_hash"),
        "content_hash": meta.get("content_hash"),
        "body_hash": meta.get("body_hash"),
        "metadata_hash": meta.get("metadata_hash"),
        "mtime_ns": meta.get("mtime_ns"),
        "size": meta.get("size"),
        "version": version,
        "first_seen": first_seen,
        "last_changed": last_changed,
        "last_changed_basis": last_changed_basis,
        "baseline": baseline,
        "warnings": warnings,
    }


def load_inventory(paths: OpsPaths) -> dict[str, Any] | None:
    data = _load_json(paths.inventory)
    if not isinstance(data, dict) or not isinstance(data.get("pages"), dict):
        return None
    return data


def _append_history(paths: OpsPaths, events: Iterable[Mapping[str, Any]]) -> int:
    events = list(events)
    if not events:
        return 0
    _ensure_dir(paths.ops)
    with paths.history.open("a", encoding="utf-8") as stream:
        for event in events:
            stream.write(_json_line(event) + "\n")
        stream.flush()
    try:
        os.chmod(paths.history, 0o600)
    except OSError:
        pass
    return len(events)


def scan(
    vault: str | Path,
    *,
    ops_dir: str | Path | None = None,
    base: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh the page inventory and append observed change events."""
    resolved_vault = Path(vault).expanduser().resolve()
    paths = ops_paths(resolved_vault, base=base, ops_dir=ops_dir)
    _ensure_dir(paths.ops)
    ensure_meta(paths, resolved_vault)
    current_time = (now or _now_local()).astimezone()
    stamp = current_time.isoformat(timespec="seconds")
    today = current_time.date()

    existing = load_inventory(paths)
    first_run = existing is None
    previous_pages: dict[str, dict[str, Any]] = existing["pages"] if existing else {}

    live: dict[str, dict[str, Any]] = {}
    for path in page_files(resolved_vault):
        page_id = path.relative_to(resolved_vault).as_posix()[:-3]
        live[page_id] = _page_meta(path, resolved_vault)

    history: list[dict[str, Any]] = []
    pages: dict[str, dict[str, Any]] = {}
    created = updated = metadata_only = renamed = deleted = unchanged = 0

    missing = set(previous_pages) - set(live)
    added = set(live) - set(previous_pages)

    rename_map: dict[str, str] = {}
    if missing and added:
        by_content: dict[str, list[str]] = defaultdict(list)
        for page_id in missing:
            by_content[str(previous_pages[page_id].get("content_hash"))].append(page_id)
        for page_id in sorted(added):
            candidates = [
                old
                for old in by_content.get(str(live[page_id].get("content_hash")), [])
                if old not in rename_map
            ]
            if len(candidates) == 1:
                rename_map[page_id] = candidates[0]
                renamed += 1

    for page_id in sorted(live):
        meta = live[page_id]
        if first_run:
            updated_date = _parse_date(meta.get("updated"))
            pages[page_id] = _inventory_entry(
                meta,
                version=1,
                first_seen=stamp,
                last_changed=updated_date.isoformat() if updated_date else None,
                last_changed_basis="frontmatter" if updated_date else "unknown",
                warnings=_static_warnings(meta, today),
                baseline=True,
            )
            continue

        if page_id in previous_pages:
            previous = previous_pages[page_id]
            warnings = _static_warnings(meta, today)
            if previous.get("file_hash") == meta.get("file_hash"):
                unchanged += 1
                carried = dict(previous)
                carried["mtime_ns"] = meta.get("mtime_ns")
                carried["size"] = meta.get("size")
                carried["warnings"] = warnings
                pages[page_id] = carried
                continue
            changes = _change_fields(previous, meta)
            substantive = previous.get("content_hash") != meta.get("content_hash")
            version = int(previous.get("version") or 1)
            if substantive:
                version += 1
                updated += 1
                last_changed = stamp
                basis = "observed"
                event_type = "updated"
            else:
                metadata_only += 1
                last_changed = previous.get("last_changed")
                basis = previous.get("last_changed_basis", "unknown")
                event_type = "metadata_only"
            pages[page_id] = _inventory_entry(
                meta,
                version=version,
                first_seen=previous.get("first_seen") or stamp,
                last_changed=last_changed,
                last_changed_basis=basis,
                warnings=sorted(set(warnings)),
            )
            history.append(
                {
                    "v": OPS_SCHEMA_VERSION,
                    "ts": stamp,
                    "event": event_type,
                    "page": page_id,
                    "from": previous.get("content_hash"),
                    "to": meta.get("content_hash"),
                    "version": version,
                    "changes": changes,
                }
            )
            continue

        if page_id in rename_map:
            old_id = rename_map[page_id]
            previous = previous_pages[old_id]
            pages[page_id] = _inventory_entry(
                meta,
                version=int(previous.get("version") or 1),
                first_seen=previous.get("first_seen") or stamp,
                last_changed=previous.get("last_changed"),
                last_changed_basis=previous.get("last_changed_basis", "unknown"),
                warnings=_static_warnings(meta, today),
            )
            history.append(
                {
                    "v": OPS_SCHEMA_VERSION,
                    "ts": stamp,
                    "event": "renamed",
                    "page": page_id,
                    "from_page": old_id,
                    "from": previous.get("content_hash"),
                    "to": meta.get("content_hash"),
                    "version": int(previous.get("version") or 1),
                    "changes": ["path"],
                }
            )
            continue

        created += 1
        pages[page_id] = _inventory_entry(
            meta,
            version=1,
            first_seen=stamp,
            last_changed=stamp,
            last_changed_basis="observed",
            warnings=_static_warnings(meta, today),
            baseline=False,
        )
        history.append(
            {
                "v": OPS_SCHEMA_VERSION,
                "ts": stamp,
                "event": "created",
                "page": page_id,
                "from": None,
                "to": meta.get("content_hash"),
                "version": 1,
                "changes": ["created"],
            }
        )

    for page_id in sorted(missing - set(rename_map.values())):
        previous = previous_pages[page_id]
        deleted += 1
        history.append(
            {
                "v": OPS_SCHEMA_VERSION,
                "ts": stamp,
                "event": "deleted",
                "page": page_id,
                "from": previous.get("content_hash"),
                "to": None,
                "version": int(previous.get("version") or 1),
                "changes": ["deleted"],
            }
        )

    inventory = {
        "schema_version": OPS_SCHEMA_VERSION,
        "generated_at": stamp,
        "vault": str(resolved_vault),
        "vault_id": paths.vault_id,
        "pages": pages,
    }
    _atomic_write_json(paths.inventory, inventory)
    history_count = _append_history(paths, history)

    return {
        "schema_version": OPS_SCHEMA_VERSION,
        "generated_at": stamp,
        "vault": str(resolved_vault),
        "ops_dir": str(paths.ops),
        "inventory": str(paths.inventory),
        "baseline": first_run,
        "pages": len(pages),
        "created": created,
        "updated": updated,
        "metadata_only": metadata_only,
        "renamed": renamed,
        "deleted": deleted,
        "unchanged": unchanged,
        "history_events": history_count,
    }


# -- report ----------------------------------------------------------------------


def _event_files(paths: OpsPaths) -> list[Path]:
    if not paths.events.is_dir():
        return []
    return sorted(path for path in paths.events.glob("*.jsonl") if path.is_file())


def _read_events(paths: OpsPaths) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    skipped = 0
    for path in _event_files(paths):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            skipped += 1
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(item, dict) or item.get("event") not in EVENT_TYPES:
                skipped += 1
                continue
            if not isinstance(item.get("page"), str) or not item["page"]:
                skipped += 1
                continue
            events.append(item)
    return events, skipped


def _read_history(paths: OpsPaths) -> list[dict[str, Any]]:
    if not paths.history.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = paths.history.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and isinstance(item.get("event"), str):
            events.append(item)
    return events


def list_events(
    vault: str | Path,
    *,
    days: int = 7,
    limit: int = 50,
    ops_dir: str | Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return recent raw events in chronological order."""
    paths = ops_paths(vault, ops_dir=ops_dir)
    all_events, _skipped = _read_events(paths)
    current = (now or _now_local()).astimezone()
    days = max(1, int(days))
    start = current.date() - timedelta(days=days - 1)
    selected = [
        event
        for event in all_events
        if (day := _event_day(event)) is not None and start <= day <= current.date()
    ]
    selected.sort(key=_event_stamp)
    return selected[-max(1, int(limit)) :]


def _event_day(event: Mapping[str, Any]) -> date | None:
    day = _parse_date(event.get("day"))
    if day:
        return day
    return _parse_date(str(event.get("ts") or ""))


def _event_stamp(event: Mapping[str, Any]) -> datetime:
    try:
        return _parse_iso(event.get("ts"))
    except OpsError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _dedupe_views(events: list[dict[str, Any]], window_minutes: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("event") != EVENT_VIEW:
            continue
        groups[
            (
                str(event.get("page")),
                str(event.get("client") or ""),
                str(event.get("source") or ""),
            )
        ].append(event)
    kept: list[dict[str, Any]] = []
    window = timedelta(minutes=max(0, window_minutes))
    for group in groups.values():
        last: datetime | None = None
        for event in sorted(group, key=_event_stamp):
            stamp = _event_stamp(event)
            if last is not None and window > timedelta(0) and stamp - last < window:
                continue
            kept.append(event)
            last = stamp
    return kept


def _page_label(page_id: str, pages: Mapping[str, Mapping[str, Any]]) -> str:
    title = str(pages.get(page_id, {}).get("title") or "").strip()
    return title or page_id.rsplit("/", 1)[-1]


def _metrics_for_pages(
    page_ids: Iterable[str],
    view_counts: Mapping[str, int],
    last_viewed: Mapping[str, str],
    pages: Mapping[str, Mapping[str, Any]],
    review_states: Mapping[str, str],
) -> list[dict[str, Any]]:
    total = sum(view_counts.values()) or 1
    rows: list[dict[str, Any]] = []
    for page_id in page_ids:
        count = int(view_counts.get(page_id, 0))
        rows.append(
            {
                "page": page_id,
                "title": _page_label(page_id, pages),
                "category": str(pages.get(page_id, {}).get("category") or ""),
                "lifecycle": str(pages.get(page_id, {}).get("lifecycle") or ""),
                "views": count,
                "share": round(count / total, 4),
                "last_viewed": last_viewed.get(page_id),
                "review_state": review_states.get(page_id, "untracked"),
            }
        )
    return rows


def _review_entries(
    vault: Path,
    pages: Mapping[str, Mapping[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    page_rows = [
        {
            "path": f"{page_id}.md",
            "lifecycle": str(meta.get("lifecycle") or ""),
            "confidence": meta.get("base_confidence"),
        }
        for page_id, meta in pages.items()
    ]
    return review_sla(page_rows, load_review_ledger(vault), now)


def _active_page(page_id: str, pages: Mapping[str, Mapping[str, Any]]) -> bool:
    meta = pages.get(page_id, {})
    return str(meta.get("lifecycle") or "") != "archived" and str(
        meta.get("operational_state") or ""
    ) != "sunset"


def _last_change_date(meta: Mapping[str, Any]) -> date | None:
    return _parse_date(str(meta.get("last_changed") or "")) or _parse_date(meta.get("updated"))


def build_report(
    vault: str | Path,
    *,
    days: int = DEFAULT_DAYS,
    top: int = DEFAULT_TOP,
    aging_days: int = DEFAULT_AGING_DAYS,
    dedupe_minutes: int = DEFAULT_DEDUPE_MINUTES,
    ops_dir: str | Path | None = None,
    base: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one operations report from the inventory and event logs."""
    resolved_vault = Path(vault).expanduser().resolve()
    paths = ops_paths(resolved_vault, base=base, ops_dir=ops_dir)
    inventory = load_inventory(paths)
    if inventory is None:
        raise OpsError("no operations inventory; run `graph-wiki ops scan` first")
    pages: dict[str, dict[str, Any]] = inventory["pages"]
    current_time = (now or _now_local()).astimezone()
    days = max(1, int(days))
    top = max(1, int(top))
    aging_days = max(1, int(aging_days))
    window_end = current_time.date()
    window_start = window_end - timedelta(days=days - 1)

    all_events, skipped = _read_events(paths)
    window_events = [
        event
        for event in all_events
        if (day := _event_day(event)) is not None and window_start <= day <= window_end
    ]
    views = [event for event in window_events if event.get("event") == EVENT_VIEW]
    retrievals = [event for event in window_events if event.get("event") == EVENT_RETRIEVAL]
    deduped = _dedupe_views(views, dedupe_minutes)

    view_counts: Counter[str] = Counter()
    view_sources: dict[str, Counter[str]] = defaultdict(Counter)
    last_viewed: dict[str, str] = {}
    last_viewed_at: dict[str, datetime] = {}
    viewers: set[str] = set()
    for event in deduped:
        page_id = str(event["page"])
        view_counts[page_id] += 1
        view_sources[page_id][str(event.get("source") or "")] += 1
        stamp = str(event.get("ts") or "")
        stamp_at = _event_stamp(event)
        if stamp and (page_id not in last_viewed_at or stamp_at >= last_viewed_at[page_id]):
            last_viewed[page_id] = stamp
            last_viewed_at[page_id] = stamp_at
        if event.get("client"):
            viewers.add(str(event["client"]))

    all_view_dates: dict[str, str] = {}
    all_view_at: dict[str, datetime] = {}
    never_viewed: set[str] = set(pages)
    for event in all_events:
        if event.get("event") != EVENT_VIEW:
            continue
        page_id = str(event["page"])
        stamp = str(event.get("ts") or "")
        stamp_at = _event_stamp(event)
        if stamp and (page_id not in all_view_at or stamp_at >= all_view_at[page_id]):
            all_view_dates[page_id] = stamp
            all_view_at[page_id] = stamp_at
        never_viewed.discard(page_id)

    retrieval_counts: Counter[str] = Counter()
    retrieval_sources: Counter[str] = Counter()
    for event in retrievals:
        retrieval_counts[str(event["page"])] += 1
        retrieval_sources[str(event.get("source") or "")] += 1

    review_entries = _review_entries(resolved_vault, pages, current_time)
    review_states: dict[str, str] = {}
    overdue: list[dict[str, Any]] = []
    due_soon: list[dict[str, Any]] = []
    for entry in review_entries:
        page_id = str(entry["page"])[:-3] if str(entry["page"]).endswith(".md") else str(entry["page"])
        review_states[page_id] = str(entry["state"])
        enriched = dict(entry)
        enriched["page"] = page_id
        enriched["title"] = _page_label(page_id, pages)
        enriched["views"] = int(view_counts.get(page_id, 0))
        if entry["state"] == "overdue":
            overdue.append(enriched)
        elif entry["state"] == "due_soon":
            due_soon.append(enriched)

    aging: list[dict[str, Any]] = []
    for page_id, meta in pages.items():
        if not _active_page(page_id, pages):
            continue
        changed = _last_change_date(meta)
        if changed is None:
            continue
        age_days = (window_end - changed).days
        if age_days >= aging_days:
            aging.append(
                {
                    "page": page_id,
                    "title": _page_label(page_id, pages),
                    "lifecycle": str(meta.get("lifecycle") or ""),
                    "last_changed": changed.isoformat(),
                    "age_days": age_days,
                    "basis": str(meta.get("last_changed_basis") or "unknown"),
                    "version": int(meta.get("version") or 1),
                    "views": int(view_counts.get(page_id, 0)),
                }
            )
    aging.sort(key=lambda item: (-int(item["age_days"]), str(item["page"])))

    history = _read_history(paths)
    window_history = [
        event
        for event in history
        if (day := _event_day(event)) is not None and window_start <= day <= window_end
    ]
    update_counts: Counter[str] = Counter()
    update_events: Counter[str] = Counter()
    changed_pages: set[str] = set()
    for event in window_history:
        kind = str(event.get("event") or "")
        update_events[kind] += 1
        page_id = str(event.get("page") or "")
        if kind == "updated":
            update_counts[page_id] += 1
            changed_pages.add(page_id)
        elif kind == "created":
            changed_pages.add(page_id)
        elif kind == "renamed":
            changed_pages.add(page_id)
        elif kind == "deleted":
            changed_pages.discard(page_id)

    metadata_health: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page_id, meta in pages.items():
        warnings = list(meta.get("warnings", []))
        if not str(meta.get("lifecycle") or "").strip():
            warnings.append("missing_lifecycle")
        if not str(meta.get("summary") or "").strip():
            warnings.append("missing_summary")
        sources = meta.get("sources")
        if not isinstance(sources, list) or not sources:
            warnings.append("missing_sources")
        changed = _parse_date(str(meta.get("last_changed") or ""))
        updated = _parse_date(meta.get("updated"))
        if (
            str(meta.get("last_changed_basis") or "") == "observed"
            and changed is not None
            and updated is not None
            and updated < changed
        ):
            warnings.append("updated_not_bumped")
        for warning in sorted(set(warnings)):
            metadata_health[str(warning)].append(
                {"page": page_id, "title": _page_label(page_id, pages)}
            )

    active_pages = sorted(page_id for page_id in pages if _active_page(page_id, pages))
    top_rows = [
        row
        for row in sorted(
            _metrics_for_pages(sorted(pages), view_counts, last_viewed, pages, review_states),
            key=lambda item: (-int(item["views"]), str(item["page"])),
        )
        if int(row["views"]) > 0
    ][:top]
    for row in top_rows:
        row["by_source"] = dict(view_sources.get(row["page"], {}))
    zero_view = [
        row
        for row in _metrics_for_pages(active_pages, view_counts, last_viewed, pages, review_states)
        if int(row["views"]) == 0
    ]
    zero_view.sort(key=lambda item: str(item["page"]))
    never_rows = [
        row
        for row in _metrics_for_pages(
            active_pages, {}, all_view_dates, pages, review_states
        )
        if row["page"] in never_viewed
    ]
    never_rows.sort(key=lambda item: str(item["page"]))

    retrieval_rows = sorted(
        (
            {
                "page": page_id,
                "title": _page_label(page_id, pages),
                "retrievals": count,
            }
            for page_id, count in retrieval_counts.items()
        ),
        key=lambda item: (-int(item["retrievals"]), str(item["page"])),
    )[:top]

    lifecycle_counts = Counter(
        str(meta.get("lifecycle") or "(missing)") for meta in pages.values()
    )
    operational_counts = Counter(
        str(meta.get("operational_state") or "(missing)") for meta in pages.values()
    )
    unknown_views = sorted(
        (
            {"page": page_id, "views": count}
            for page_id, count in view_counts.items()
            if page_id not in pages
        ),
        key=lambda item: (-int(item["views"]), str(item["page"])),
    )
    top_pages = {str(row["page"]) for row in top_rows if int(row["views"]) > 0}
    signals: list[dict[str, Any]] = []
    for entry in overdue:
        if entry["page"] in top_pages:
            signals.append(
                {
                    "kind": "popular_review_overdue",
                    "severity": "high",
                    "page": entry["page"],
                    "message": (
                        f"{entry['views']} view(s) this window but review is "
                        f"{entry['days_overdue']} day(s) overdue"
                    ),
                }
            )
    for row in top_rows[:5]:
        meta = pages.get(str(row["page"]), {})
        if int(row["views"]) > 0 and not str(meta.get("summary") or "").strip():
            signals.append(
                {
                    "kind": "popular_missing_summary",
                    "severity": "medium",
                    "page": row["page"],
                    "message": "frequently viewed page has no summary",
                }
            )
    for entry in aging:
        if int(entry["views"]) == 0 and len(signals) < 20:
            signals.append(
                {
                    "kind": "aging_zero_view",
                    "severity": "low",
                    "page": entry["page"],
                    "message": f"no views this window and no substantive change for {entry['age_days']} day(s)",
                }
            )
    for warning, entries in metadata_health.items():
        for entry in entries[:5]:
            if len(signals) >= 40:
                break
            signals.append(
                {
                    "kind": f"metadata_{warning}",
                    "severity": "medium",
                    "page": entry["page"],
                    "message": warning.replace("_", " "),
                }
            )

    return {
        "schema_version": OPS_SCHEMA_VERSION,
        "generated_at": current_time.isoformat(timespec="seconds"),
        "vault": {"path": str(resolved_vault), "id": paths.vault_id},
        "window": {
            "days": days,
            "from": window_start.isoformat(),
            "to": window_end.isoformat(),
        },
        "tracking": {
            "since": (_load_json(paths.meta) or {}).get("created_at"),
            "pages": len(pages),
            "events": len(all_events),
            "skipped_lines": skipped,
            "ops_dir": str(paths.ops),
        },
        "inventory": {
            "lifecycle": dict(sorted(lifecycle_counts.items())),
            "operational_state": dict(sorted(operational_counts.items())),
        },
        "views": {
            "total": len(deduped),
            "raw": len(views),
            "viewers": len(viewers),
            "dedupe_minutes": dedupe_minutes,
            "by_source": dict(Counter(str(event.get("source") or "") for event in deduped)),
            "top": top_rows,
            "zero_view": zero_view[:top],
            "zero_view_pages": len(zero_view),
            "never_viewed": never_rows[:top],
            "never_viewed_pages": len(never_rows),
            "unknown": unknown_views[:top],
            "unknown_pages": len(unknown_views),
        },
        "retrievals": {
            "total": len(retrievals),
            "by_source": dict(retrieval_sources),
            "top": retrieval_rows,
        },
        "updates": {
            "pages": len(changed_pages),
            "events": len(window_history),
            "by_kind": dict(update_events),
            "top": [
                {
                    "page": page_id,
                    "title": _page_label(page_id, pages),
                    "changes": count,
                    "version": int(pages.get(page_id, {}).get("version") or 1),
                }
                for page_id, count in sorted(
                    update_counts.items(), key=lambda item: (-item[1], item[0])
                )[:top]
            ],
        },
        "versions": {
            "tracked": len(pages),
            "changed_pages": len(changed_pages),
            "max_version": max((int(meta.get("version") or 1) for meta in pages.values()), default=1),
        },
        "expiry": {
            "aging_days": aging_days,
            "review_overdue": overdue,
            "review_due_soon": due_soon,
            "overdue_pages": len(overdue),
            "due_soon_pages": len(due_soon),
            "aging": aging[: max(top, DEFAULT_TOP)],
            "aging_pages": len(aging),
        },
        "metadata_health": {
            key: entries
            for key, entries in sorted(metadata_health.items())
        },
        "signals": signals[:20],
    }


def compare_reports(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(previous, Mapping):
        return {
            "status": "first_run",
            "previous_generated_at": None,
            "counts": {},
        }
    previous_views = int(previous.get("views", {}).get("total", 0) or 0)
    current_views = int(current.get("views", {}).get("total", 0) or 0)
    previous_retrievals = int(previous.get("retrievals", {}).get("total", 0) or 0)
    current_retrievals = int(current.get("retrievals", {}).get("total", 0) or 0)
    previous_overdue = int(previous.get("expiry", {}).get("overdue_pages", 0) or 0)
    current_overdue = int(current.get("expiry", {}).get("overdue_pages", 0) or 0)
    previous_aging = int(previous.get("expiry", {}).get("aging_pages", 0) or 0)
    current_aging = int(current.get("expiry", {}).get("aging_pages", 0) or 0)
    counts = {
        "views": current_views - previous_views,
        "retrievals": current_retrievals - previous_retrievals,
        "review_overdue": current_overdue - previous_overdue,
        "aging": current_aging - previous_aging,
    }
    status = "stable" if all(value == 0 for value in counts.values()) else "changed"
    return {
        "status": status,
        "previous_generated_at": previous.get("generated_at"),
        "counts": counts,
    }


def save_report(path: str | Path, report: Mapping[str, Any], *, vault: str | Path | None = None) -> Path:
    destination = Path(path).expanduser().resolve()
    if vault is not None:
        resolved_vault = Path(vault).expanduser().resolve()
        if destination == resolved_vault or resolved_vault in destination.parents:
            raise OpsError("operations snapshots must be stored outside the vault")
    snapshot = {key: value for key, value in report.items() if key != "delta"}
    _atomic_write_json(destination, snapshot)
    return destination


def load_report(path: str | Path) -> dict[str, Any] | None:
    data = _load_json(Path(path).expanduser())
    if isinstance(data, dict) and isinstance(data.get("views"), dict):
        return data
    return None


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact human report from a report payload."""
    lines: list[str] = []
    window = report.get("window", {})
    lines.append(f"# Wiki operations — {report.get('vault', {}).get('path', '')}")
    lines.append("")
    lines.append(
        f"Window: {window.get('from')} to {window.get('to')} "
        f"({window.get('days')} days) · generated {report.get('generated_at')}"
    )
    lines.append("")
    tracking = report.get("tracking", {})
    views = report.get("views", {})
    retrievals = report.get("retrievals", {})
    updates = report.get("updates", {})
    expiry = report.get("expiry", {})
    meta = report.get("metadata_health", {})
    lines.append("## Overview")
    lines.append("")
    inventory = report.get("inventory", {})
    lines.append(f"- Pages tracked: {tracking.get('pages', 0)}")
    lines.append(
        f"- Lifecycle: {inventory.get('lifecycle', {})} · operational state: "
        f"{inventory.get('operational_state', {})}"
    )
    lines.append(
        f"- Views: {views.get('total', 0)} deduped ({views.get('raw', 0)} raw, "
        f"{views.get('viewers', 0)} viewer(s)); by source: {views.get('by_source', {})}"
    )
    lines.append(
        f"- Retrievals: {retrievals.get('total', 0)}; by source: {retrievals.get('by_source', {})}"
    )
    lines.append(
        f"- Updates: {updates.get('pages', 0)} page(s), {updates.get('events', 0)} event(s) "
        f"{updates.get('by_kind', {})}"
    )
    lines.append(
        f"- Review overdue: {expiry.get('overdue_pages', 0)} · due soon: "
        f"{expiry.get('due_soon_pages', 0)} · aging ≥ {expiry.get('aging_days')} days: "
        f"{expiry.get('aging_pages', 0)}"
    )
    if meta:
        lines.append(f"- Metadata warnings: {sum(len(v) for v in meta.values())}")
    delta = report.get("delta")
    if isinstance(delta, Mapping):
        lines.append(f"- Delta: {delta.get('status')} {delta.get('counts')}")
    lines.append("")

    def table(rows: Iterable[Mapping[str, Any]], columns: tuple[tuple[str, str], ...]) -> None:
        lines.append("| " + " | ".join(label for _, label in columns) + " |")
        lines.append("|" + "|".join("---" for _ in columns) + "|")
        for row in rows:
            values = []
            for key, _ in columns:
                value = row.get(key, "")
                if value is None:
                    value = ""
                values.append(str(value).replace("|", "\\|"))
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")

    lines.append("## Most viewed")
    if views.get("top"):
        table(views["top"], (("title", "Page"), ("page", "Path"), ("views", "Views"), ("last_viewed", "Last viewed"), ("review_state", "Review")))
    else:
        lines.append("No views recorded in this window.")
        lines.append("")

    lines.append("## Retrievals")
    if retrievals.get("top"):
        table(retrievals["top"], (("title", "Page"), ("page", "Path"), ("retrievals", "Retrievals")))
    else:
        lines.append("No retrieval events recorded in this window.")
        lines.append("")

    lines.append("## Zero-view and never-viewed")
    lines.append(f"- Zero views this window: {views.get('zero_view_pages', 0)}")
    lines.append(f"- Never viewed since tracking started: {views.get('never_viewed_pages', 0)}")
    if views.get("unknown_pages"):
        lines.append(
            f"- Views for pages not in the current inventory: {views.get('unknown_pages')}"
        )
    if views.get("zero_view"):
        table(views["zero_view"], (("title", "Page"), ("page", "Path"), ("lifecycle", "Lifecycle")))
    lines.append("")

    lines.append("## Updates and versions")
    if updates.get("top"):
        table(updates["top"], (("title", "Page"), ("page", "Path"), ("changes", "Changes"), ("version", "Version")))
    else:
        lines.append("No page changes detected in this window.")
        lines.append("")

    lines.append("## Expiry and review")
    if expiry.get("review_overdue"):
        table(expiry["review_overdue"], (("title", "Page"), ("page", "Path"), ("due", "Due"), ("days_overdue", "Days overdue"), ("views", "Views")))
    else:
        lines.append("No overdue reviews.")
        lines.append("")
    if expiry.get("review_due_soon"):
        table(expiry["review_due_soon"], (("title", "Page"), ("page", "Path"), ("due", "Due"), ("views", "Views")))
    if expiry.get("aging"):
        lines.append(f"Aging pages (no substantive change for ≥ {expiry.get('aging_days')} days):")
        lines.append("")
        table(expiry["aging"], (("title", "Page"), ("page", "Path"), ("last_changed", "Last change"), ("age_days", "Days"), ("views", "Views")))

    lines.append("## Metadata health")
    if meta:
        for warning, entries in meta.items():
            lines.append(f"- {warning}: {len(entries)}")
            for entry in entries[:5]:
                lines.append(f"  - {entry.get('page')}")
    else:
        lines.append("No metadata warnings.")
    lines.append("")

    lines.append("## Recommended actions")
    if report.get("signals"):
        for signal in report["signals"]:
            lines.append(
                f"- [{signal.get('severity')}] {signal.get('page')}: {signal.get('message')}"
            )
    else:
        lines.append("No action signals.")
    lines.append("")
    return "\n".join(lines)


# -- instrumentation helpers -----------------------------------------------------


def record_retrieval(
    vault: str | Path,
    pages: Iterable[str],
    source: str,
    *,
    config: Mapping[str, str] | None = None,
    ops_dir: str | Path | None = None,
) -> int:
    """Record one retrieval event per distinct returned page, if enabled."""
    if not ops_enabled(config):
        return 0
    normalized = []
    for page in pages:
        try:
            value = _normalize_page(page)
        except OpsError:
            continue
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        return 0
    events = [
        {
            "event": EVENT_RETRIEVAL,
            "page": page,
            "source": source,
            "client": "agent",
        }
        for page in normalized
    ]
    try:
        result = record_events(vault, events, ops_dir=ops_dir)
    except (OpsError, OSError):
        return 0
    return int(result["accepted"])


class OpsRecorder:
    """Thread-safe collector used by the Graph Viewer process.

    Appends are one ``os.write`` per line, so concurrent requests cannot
    interleave bytes.  Recording failures never fail the page response.
    """

    def __init__(self, vault: str | Path, *, ops_dir: str | Path | None = None) -> None:
        self.vault = Path(vault).expanduser().resolve()
        self.paths = ops_paths(self.vault, ops_dir=ops_dir)
        _ensure_dir(self.paths.ops)
        ensure_meta(self.paths, self.vault)
        self.token = ensure_token(self.paths)

    def record(
        self,
        event: str,
        page: str,
        client: str = "",
        *,
        source: str = "viewer",
    ) -> bool:
        try:
            record_events(
                self.vault,
                [{"event": event, "page": page, "source": source, "client": client}],
                ops_dir=self.paths.ops,
            )
        except (OpsError, OSError, ValueError):
            return False
        return True

    def record_view(self, page: str, client: str, *, source: str = "viewer") -> bool:
        return self.record(EVENT_VIEW, page, client, source=source)


def bundled_obsidian_plugin() -> Path:
    package = Path(__file__).resolve().parent
    for candidate in (
        package / "_data" / "extensions" / "obsidian-ops",
        package.parent / "extensions" / "obsidian-ops",
    ):
        if (candidate / "manifest.json").is_file() and (candidate / "main.js").is_file():
            return candidate
    raise OpsError("bundled Obsidian plugin is missing from this installation")


def install_obsidian_plugin(
    vault: str | Path,
    *,
    port: int = 8765,
    ops_dir: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Copy the bundled plugin into the vault and write its local settings."""
    resolved_vault = Path(vault).expanduser().resolve()
    if not resolved_vault.is_dir():
        raise OpsError(f"vault not found: {resolved_vault}")
    source = bundled_obsidian_plugin()
    paths = ops_paths(resolved_vault, ops_dir=ops_dir)
    _ensure_dir(paths.ops)
    ensure_meta(paths, resolved_vault)
    token = ensure_token(paths)
    target = resolved_vault / ".obsidian" / "plugins" / "graph-wiki-ops"
    _ensure_dir(target)
    for name in ("manifest.json", "main.js", "README.md"):
        source_file = source / name
        if source_file.is_file():
            shutil.copyfile(source_file, target / name)
    settings_path = target / "data.json"
    existing = _load_json(settings_path)
    client_id = ""
    if isinstance(existing, dict) and not force:
        client_id = str(existing.get("clientId") or "")
    if not client_id:
        client_id = "obsidian-" + secrets.token_hex(8)
    settings = {
        "serverUrl": f"http://127.0.0.1:{int(port)}",
        "port": int(port),
        "token": token,
        "clientId": client_id,
    }
    _atomic_write_json(settings_path, settings)
    return {
        "plugin_dir": str(target),
        "settings": str(settings_path),
        "port": int(port),
        "client_id": client_id,
        "ops_dir": str(paths.ops),
    }
