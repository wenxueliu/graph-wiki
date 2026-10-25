#!/usr/bin/env bash
set -euo pipefail

# Daily wiki index update — called by launchd or directly.
# Checks if any history sources are stale and writes vault-scoped state files
# that the shell prompt reads on terminal open.
#
# Config resolution order (mirrors llm-wiki/SKILL.md protocol):
#   1. Walk up from CWD looking for .env with OBSIDIAN_VAULT_PATH
#   2. Fall back to <config-dir>/config, where the config directory comes from
#      GRAPH_WIKI_CONFIG_DIR (environment or nearest .env) and defaults to
#      ~/.graph-wiki
#   3. Exit with error if neither found

_resolve_config_dir() {
  local value="${GRAPH_WIKI_CONFIG_DIR:-}"
  if [[ -n "$value" ]]; then
    [[ "$value" = /* ]] || value="$PWD/$value"
    echo "$value"
    return
  fi
  local dir="$PWD"
  while [[ "$dir" != "$HOME" && "$dir" != "/" ]]; do
    if [[ -f "$dir/.env" ]]; then
      value=$(grep -E '^GRAPH_WIKI_CONFIG_DIR=' "$dir/.env" | head -1 | cut -d= -f2- \
        | sed -e "s/^[\"']//" -e "s/[\"']$//")
      if [[ -n "$value" ]]; then
        [[ "$value" = /* ]] || value="$dir/$value"
        echo "$value"
        return
      fi
    fi
    dir="$(dirname "$dir")"
  done
  echo "$HOME/.graph-wiki"
}

_find_config() {
  local dir="$PWD"
  while [[ "$dir" != "$HOME" && "$dir" != "/" ]]; do
    if [[ -f "$dir/.env" ]] && grep -q "OBSIDIAN_VAULT_PATH" "$dir/.env" 2>/dev/null; then
      echo "$dir/.env"
      return
    fi
    dir="$(dirname "$dir")"
  done
  local config_dir
  config_dir="$(_resolve_config_dir)"
  if [[ -f "$config_dir/config" ]]; then
    echo "$config_dir/config"
    return
  fi
  echo ""
}

CONFIG_FILE="$(_find_config)"

if [[ -z "$CONFIG_FILE" ]]; then
  echo "[wiki-daily] No config found. Run wiki-setup to initialize your wiki." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
  echo "[wiki-daily] OBSIDIAN_VAULT_PATH not set in $CONFIG_FILE — skipping" >&2
  exit 1
fi

# Vault-scoped state dir (supports multiple vaults independently)
VAULT_ID=$(echo "$OBSIDIAN_VAULT_PATH" | md5sum 2>/dev/null | cut -c1-8 || \
           md5 -q - <<< "$OBSIDIAN_VAULT_PATH" 2>/dev/null | cut -c1-8 || \
           echo "default")
STATE_DIR="$HOME/.graph-wiki/state/$VAULT_ID"
mkdir -p "$STATE_DIR"

# Write vault path so wiki-notify.sh can find this state dir
echo "$OBSIDIAN_VAULT_PATH" > "$STATE_DIR/.vault_path"

MANIFEST="$OBSIDIAN_VAULT_PATH/.manifest.json"

# Count sources modified after last ingest
stale_count=0
if [[ -f "$MANIFEST" ]]; then
  last_updated=$(python3 -c "
import json, sys
try:
  d = json.load(open('$MANIFEST'))
  print(d.get('last_updated',''))
except:
  print('')
" 2>/dev/null || echo "")

  if [[ -n "$last_updated" ]]; then
    stale_count=$(MANIFEST="$MANIFEST" OBSIDIAN_VAULT_PATH="$OBSIDIAN_VAULT_PATH" python3 - <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone

manifest_path = os.environ["MANIFEST"]
try:
    with open(manifest_path) as f:
        manifest = json.load(f)
except Exception:
    print(0)
    sys.exit()

last_updated_str = manifest.get("last_updated", "")
try:
    last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
except Exception:
    print(0)
    sys.exit()
if last_updated.tzinfo is None:
    last_updated = last_updated.replace(tzinfo=timezone.utc)

vault_path = os.environ.get("OBSIDIAN_VAULT_PATH", "")
stale = 0
for path, meta in manifest.get("sources", {}).items():
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded) and vault_path:
        expanded = os.path.join(vault_path, expanded)
    if os.path.exists(expanded):
        mtime = datetime.fromtimestamp(os.path.getmtime(expanded), tz=timezone.utc)
        if mtime > last_updated:
            stale += 1

print(stale)
PYEOF
    )
  fi
fi

# Write vault-scoped state
NOW=$(date +%s)
echo "$NOW" > "$STATE_DIR/.last_update"
echo "$stale_count" > "$STATE_DIR/.pending_delta"

if [[ "$stale_count" -gt 0 ]]; then
  echo "[wiki-daily] $stale_count source(s) have new content since last ingest. State: $STATE_DIR"
else
  echo "[wiki-daily] Wiki is up to date. State: $STATE_DIR"
fi
