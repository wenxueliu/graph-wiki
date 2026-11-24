English | [简体中文](quality.zh-CN.md)

# Knowledge Quality Control

A wiki can grow quickly and still become untrustworthy. Quality control keeps the vault
auditable as it grows: every durable claim should trace back to a source, every page should obey the
active contract, unresolved disagreement should stay visible, and a human should be able to say
which confidence values were actually reviewed.

`graph-wiki quality` turns those concerns into one deterministic, gate-ready report. It is an
aggregation layer over existing checks, not a replacement for them:

- `graph-wiki lint` owns structural, schema, and relationship findings.
- `graph-wiki trust-check` owns confidence and review-ledger integrity.
- `graph-wiki verify` owns manifest-to-page coverage.
- `graph-wiki pack eval` owns retrieval quality.
- `graph-wiki quality` combines them with source and provenance coverage into one status.

## The quality model

| Dimension | What it asks | Deterministic signals |
|---|---|---|
| Structure | Is the page set schema-valid and connected? | broken links, missing frontmatter, missing summaries, oversized pages |
| Traceability | Can a claim be traced to evidence? | pages without sources, pages without provenance, invalid provenance blocks, provenance drift |
| Consistency | Is the graph free of obvious duplicates and dead ends? | duplicate title groups, orphan pages, typed-relationship issues |
| Coverage | Did every recorded source actually produce its pages? | manifest sources, sources with no pages, phantom pages |
| Freshness | Is the lifecycle still honest? | lifecycle distribution, missing lifecycle, reviews whose material fingerprint changed |
| Trust | Was confidence reviewed by a human? | ledger presence, missing trust fields, ledger errors, score mismatches, stale and unreviewed pages |
| Retrieval | Can the knowledge be found and used? | reported as `not_measured` until `pack eval` results are wired in |

Each dimension returns `pass`, `warn`, `fail`, or `not_measured`. The overall status is `fail` if any
dimension fails, `warn` if any dimension warns, and `pass` otherwise. `not_measured` never
silently becomes a pass: it is printed as its own state and carries a note explaining what to run.

## Gates, not a single score

Quality is enforced at four boundaries. The asymmetry is deliberate: capture should be forgiving,
publishing should be strict.

| Gate | When it runs | Commands | Failure behavior |
|---|---|---|---|
| G0 Ingest | A source enters the vault | Knowledge Pack scope check, `text-document-*` / `text-ingest-*` | Reject or stage; never write a partial knowledge page |
| G1 Write | A page is created or merged | `validate`, page contract, canonical-merge check | Block the write and retry |
| G2 Release | A vault state is published as a Content Pack | `lint`, `quality`, `trust-check`, `pack verify`, `pack eval` | Do not publish |
| G3 Runtime | Queries and periodic maintenance | lifecycle-aware ranking, `daily-update`, `wiki-lint` semantic audit | Hide retired pages, demote unsettled ones, queue repairs |

`quality` is the G2 aggregator. It does not modify the vault; it reads the same files and returns an
exit code suitable for CI.

## Running the check

```bash
graph-wiki quality                     # configured vault, human-readable summary
graph-wiki quality /path/to/vault      # explicit vault
graph-wiki quality @research --json    # named profile, machine-readable report
graph-wiki quality --pretty --json
graph-wiki quality --strict            # warnings also exit non-zero
graph-wiki quality --require-trust-ledger   # release gate: no ledger means fail
graph-wiki quality --strict-trust      # schema gaps and stale reviews fail
graph-wiki quality --allow-lifecycle active \
  --schema-source /path/to/vault/AGENTS.md
```

Exit codes: `0` for `pass` (and for `warn` unless `--strict`), `1` for `fail` or for `warn` under
`--strict`. The command resolves the vault and schema exactly like `lint`.

### Report shape

```json
{
  "status": "warn",
  "generated_at": "2026-11-24T12:30:33+00:00",
  "vault": "/abs/path/to/vault",
  "schema": {"source": "framework-defaults", "allowed_lifecycles": ["..."], "...": "..."},
  "gate": {
    "strict_trust": false,
    "require_trust_ledger": false,
    "failed_dimensions": [],
    "warned_dimensions": ["traceability"]
  },
  "stats": {"pages": 42, "total_tokens": 31840, "manifest_sources": 7, "...": "..."},
  "dimensions": {
    "structure": {"status": "pass", "signals": {"broken_links": 0}, "notes": []},
    "traceability": {"status": "warn", "signals": {"missing_provenance": 3}, "notes": ["..."]},
    "trust": {"status": "not_measured", "signals": {"ledger_configured": 0}, "notes": ["..."]}
  },
  "metrics": {"lifecycle": {"draft": 4, "reviewed": 38}, "provenance": {"...": "..."}},
  "findings": {"broken_links": [], "traceability": {"missing_sources": []}, "coverage": {}}
}
```

`findings` keeps the detailed lists so a CI job or dashboard can render paths, not just counts.
`metrics` carries the trend-friendly numbers: lifecycle counts, provenance means, marker counts,
duplicate-title groups, oversized pages, and index-cache consistency.

## Severity policy

| Dimension | Fails when | Warns when |
|---|---|---|
| Structure | broken link or missing core frontmatter | missing summary, page above the token ceiling |
| Traceability | — | missing sources, missing/invalid provenance block, provenance drift |
| Consistency | — | duplicate title groups, orphan pages, relationship issues |
| Coverage | manifest entry with no pages, or a phantom page | — |
| Freshness | — | missing lifecycle, review older than the page's material fingerprint |
| Trust | invalid trust metadata, corrupt ledger, score mismatch | missing trust fields, stale or unreviewed pages |
| Retrieval | — | — (`not_measured` until pack evaluation is wired in) |

Thresholds match the semantic audit in the `wiki-lint` workflow: ambiguous content above `15%`,
inferred content above `40%` on a page with no sources, and a page lifecycle outside the resolved
allowlist all surface as findings.

## What remains human

Deterministic checks can prove that a page cites a source. They cannot prove that the source
supports the claim. That judgment stays with a person, and the trust ledger is the record of it:

```bash
graph-wiki trust-record --all --reviewed-at 2026-11-24T10:00:00+00:00 --approved
graph-wiki trust-check --strict
```

`quality` reports the ledger's state but never writes it and never recomputes confidence from URLs.
Agent-driven semantic work — contradiction detection, provenance classification, synthesis gaps —
stays in the `wiki-lint` skill.

## CI example

```yaml
- name: Install
  run: pip install graph-wiki-skills
- name: Knowledge quality gate
  run: graph-wiki quality "$VAULT" --strict --require-trust-ledger --json
```

Run `quality` after ingest and before publishing a Content Pack. For a repository that only ships
skills, the same command can gate a fixture vault in CI.

## Current scope

Shipped in this release:

- the deterministic `quality` report and CLI;
- source/provenance/lifecycle aggregation;
- trust-ledger and manifest-coverage gating;
- `--strict`, `--strict-trust`, and `--require-trust-ledger` gate modes.

Planned next:

- citation-locator resolution (source path plus line or anchor);
- semantic duplicate and contradiction signals shared with the `wiki-lint` workflow;
- answer-grounding evaluation alongside retrieval metrics;
- per-vault threshold overrides and trend baselines.

`quality` is a gate, not a grade. It is designed to stop known-bad states and surface missing
evidence, not to declare that a page is correct.
