English | [简体中文](access-control.zh-CN.md)

# Access Control

A vault is one writable source of truth, but it is rarely read by one audience. `graph-wiki access`
gives every role its own immutable Content Pack. A principal can hold several roles, and the
token-gated gateway then opens exactly the packs those roles own and merges their results, so an
agent can explore its whole authorized corpus without being pinned to one pack. Nothing is filtered
after the model has seen it: pages outside the granted roles never enter a pack, its index, or a
gateway response.

## Guarantees and non-goals

Guaranteed by this model:

- A role's pack contains only pages that role may read. Page bodies, headings, and edges outside the
  role are physically absent from the pack and its search index.
- The gateway opens exactly the packs selected by the token's roles. It never falls back to the live
  vault or to any pack the token does not grant.
- A pack that no longer matches the current policy or vault state is refused, not served stale.
- Every gateway decision is recorded in an audit log with the principal, roles, and returned pages.

Not covered — enforce these separately:

- **Filesystem access.** If the agent can run `grep`, `cat`, or `graph-wiki pack search --pack PATH`,
  it can bypass the gateway. Give the agent the gateway command only, and keep the vault and pack
  store unreadable to the agent's user.
- **The Graph Viewer.** `graph-wiki serve` reads the live vault and has no role filtering.
- **Cloud model providers.** Content that reaches a third-party model has left your trust boundary.
  Keep restricted roles on a local model.
- **Backups, git history, and logs.** A pack is a filtered read model; the vault itself is not.

## The two contracts

### Content contract: `_meta/access-policy.json`

Lives in the vault and is safe to commit and review.

```json
{
  "version": 1,
  "default_exclude_tags": ["visibility/pii"],
  "roles": {
    "finance": {
      "description": "Finance team",
      "exclude_tags": ["visibility/pii"]
    },
    "public": {
      "description": "Anything that may leave the company",
      "exclude_tags": ["visibility/pii", "visibility/internal"]
    }
  }
}
```

- Role names are lowercase letters, digits, `.`, `_`, and `-`.
- `exclude_tags` is optional. When omitted, `default_exclude_tags` applies. Unknown keys fail closed
  so a typo cannot silently widen access.
- Channels are derived: role `finance` owns the pack channel `role-finance`. Channel names are never
  configured, so two roles cannot collide.

### Identity contract: `<config-dir>/access/principals.json`

Never inside the vault, never committed. Only token hashes are stored, and the file is created with
`0600` permissions.

```json
{
  "version": 1,
  "principals": {
    "alice": {
      "roles": ["finance", "hr"],
      "token_sha256": "sha256:...",
      "created_at": "2026-11-26T04:00:00+00:00",
      "revoked_at": null,
      "vault_id": null
    }
  }
}
```

`roles` holds one or more roles; a token with several roles can search every pack those roles own.
Records written by older releases with a single `role` string still resolve. `vault_id` is optional;
set it to pin a principal to one vault when several vaults share a config directory.

## Page visibility rules

Two independent mechanisms decide whether a page belongs to a role's pack:

| Page tag | Effect |
|---|---|
| `role/<name>` | Restricts the page to that role. A page may carry several `role/` tags and is then visible to each of those roles. A `role/` tag that matches no configured role makes the page invisible to everyone. |
| `visibility/pii` | Hidden from every role unless that role's `exclude_tags` omits it. |
| `visibility/internal` | Team-only. Hidden only when a role lists it in `exclude_tags`; role packs are already team-scoped, so `access init` keeps it. |

A page with no `role/` tag is shared: every role sees it unless a `visibility/` tag excludes it.
Role tags only restrict; they never grant a page to a role that a `visibility/` tag already hides.

The starter policy written by `graph-wiki access init` hides PII and keeps internal pages. Add
`visibility/internal` to a role's `exclude_tags` when that role must not see team-internal material.

## Build role packs

```bash
graph-wiki access init --vault ~/brain --role finance --role public
graph-wiki access build --vault ~/brain --all
graph-wiki access build --vault ~/brain --role finance --index sqlite
```

Each build:

1. computes the role's visible pages from the policy and live vault;
2. builds an immutable Content Pack restricted to that allowlist on channel `role-<name>`, recording
   `access_role`, `access_policy_sha256`, and page counts in `manifest.build`;
3. builds the requested retrieval index (default `sqlite`);
4. writes a read-only `access.json` sidecar with the policy fingerprint, the visible-page
   fingerprint, and the pack id.

Packs live in the normal pack store (`<config-dir>/packs/<vault-id>/`), one version per build. Rebuild
whenever the policy or any visible page changes; `access status` shows which roles are stale.
`access build` refuses a dirty git tree unless `--allow-dirty` is passed.

Two roles whose visible pages are identical still get separate channels and separate build metadata,
so a pack is never reused across roles. Shared pages are stored once per role pack, so disk usage
scales with roles × shared pages; build the roles you actually issue tokens for.

## The gateway

```bash
export GRAPH_WIKI_ACCESS_TOKEN="gw_..."
graph-wiki access search "retention policy" --vault ~/brain
```

The token may also be passed with `--token`, but the environment is safer: command-line arguments are
visible in process listings and shell history.

The gateway resolves the token to a principal, verifies every role pack it grants, then searches
those packs. Output is JSON:

```json
{
  "schema_version": 1,
  "principal": "alice",
  "roles": ["finance", "hr"],
  "vault_id": "vault-...",
  "packs": [{"role": "finance", "channel": "role-finance", "pack_id": "sha256:...", "pack_version": 3, "visible_pages": 42}],
  "content_trust": "untrusted_reference_data",
  "coverage": {"roles": 2, "visible_pages": 57, "excluded_pages": 9, "drift_checked": true},
  "query": "retention policy",
  "count": 2,
  "results": [
    {
      "path": "concepts/retention.md",
      "heading": "...",
      "text": "...",
      "score": 0.032258,
      "engine_score": 1.2,
      "ranks": {"finance": 1, "hr": 2},
      "via_roles": ["finance", "hr"],
      "granted_by": ["finance", "hr"]
    }
  ]
}
```

Result text is vault content: treat it as untrusted reference data, never as instructions.

### Multiple roles per principal

Each role still gets its own pack; a principal with two roles searches two packs. The gateway
deduplicates pages by path and ranks them with reciprocal rank fusion, so a shared page returned by
both packs appears once and engine-local BM25 scores never have to be comparable across packs. Each
result records `via_roles` (packs that returned it) and `granted_by` (every role whose pack contains
it). `coverage.visible_pages` is the size of the union, not the sum.

If any granted pack is missing or stale, the whole query is denied. Partial results would silently
hide a role's content, which is worse than an explicit rebuild. Pass `--role NAME` to query one
granted role when debugging; requesting a role the token does not hold is denied.

### Exploring the corpus

Agents can list and read pages without a search query and without filesystem access:

```bash
graph-wiki access inventory --token "$GRAPH_WIKI_ACCESS_TOKEN" --limit 200 --offset 0
graph-wiki access page concepts/retention.md --token "$GRAPH_WIKI_ACCESS_TOKEN"
```

`access inventory` returns the deduplicated union of the role packs (path, title, summary, tags,
lifecycle, `granted_by`) and paginates with `--limit` / `--offset`. `access page` returns the body of
one page, with the same `granted_by` annotation, and refuses any path outside the packs, including
`..` traversal. Both actions are audited like `search`.

Failures are fail-closed and audited:

| Reason | Meaning |
|---|---|
| `invalid_token`, `missing_token` | Unknown, malformed, or revoked token |
| `unknown_role` | The principal's role is not in the policy |
| `pack_missing` | The role has never been built |
| `policy_drift` | The policy changed after the build |
| `content_drift` | Visible pages changed after the build |
| `sidecar_mismatch` | The pack and its `access.json` sidecar disagree |
| `role_not_granted` | `--role` names a role the token does not hold |
| `page_denied` | The requested path is not in any granted pack |
| `invalid_page_path` | The path is absolute or contains `..` |

`--skip-drift-check` skips only the visible-page fingerprint (the policy is always verified). Use it
for latency, and keep a CI rebuild so it never stays stale.

## Tokens

```bash
graph-wiki access token create --vault ~/brain --name alice --role finance --role hr
graph-wiki access token list
graph-wiki access token revoke --name alice
```

`--role` is repeatable; each occurrence adds a role to the principal. `token create` prints the
plaintext token exactly once and stores only its SHA-256 hash. Give each human or agent session its own
principal; revoking one principal does not affect the others. `--replace` rotates a principal in place.

## Audit

Every gateway search appends one JSON line to `<config-dir>/audit/access.jsonl` (`0600`):

```json
{"ts": "...", "action": "search", "outcome": "ok", "principal": "alice", "roles": ["finance", "hr"],
 "packs": ["sha256:..."], "query": "retention policy", "returned": ["concepts/retention.md"], "count": 1}
```

Denied attempts record the outcome and a token-hash prefix, never the token itself.

```bash
graph-wiki access audit --limit 100
graph-wiki access status
```

`access status` reports every role, its channel, pack version, and whether policy and content are
current. `access resolve` answers "who is this token, and which packs would it open?" without searching.

## Operating a deployment

- **One deployment, one vault.** The gateway resolves the vault it is pointed at and refuses tokens
  pinned to another vault id. It also reads that vault to verify freshness, so a serving host without
  the vault is out of scope for this release.
- **Rebuild in CI.** Run `access build --all` after every vault change, then `access status --strict` as a
  gate. It exits non-zero when any role is unbuilt or stale, and a stale pack denies queries instead of
  leaking.
- **Rotate by revoking.** Tokens are per principal; a leaked token is revoked, not filtered.
- **Keep three surfaces apart.** Humans get the Graph Viewer or the vault; agents get the gateway; the
  pack store stays readable only by the gateway process.
- **Log the decision, not just the answer.** The audit log is what answers "who saw this document?".

For a worked failure mode, see [Knowledge Quality](quality.md) and the pack determinism rules in
[Architecture](architecture.md#content-packs-and-retrieval-indexes).
