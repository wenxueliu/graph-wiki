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
| G1 Write | A page is created or merged | `page-check`, `validate`, page contract, canonical-merge check | Block the write and retry |
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
graph-wiki quality --baseline "$state/quality-latest.json" \
  --save "$state/quality-latest.json"  # daily delta
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
  "metrics": {
    "lifecycle": {"draft": 4, "reviewed": 38},
    "provenance": {"...": "..."},
    "review": {"tracked": 42, "overdue": 2, "due_soon": 1},
    "contradictions": 1,
    "duplicate_candidates": 3
  },
  "findings": {
    "broken_links": [],
    "traceability": {"missing_sources": []},
    "coverage": {},
    "review_overdue": [],
    "contradictions": [],
    "duplicate_candidates": []
  }
}
```

`findings` keeps the detailed lists so a CI job or dashboard can render paths, not just counts.
`metrics` carries the trend-friendly numbers: lifecycle counts, provenance means, marker counts,
duplicate-title groups, oversized pages, and index-cache consistency.

## Write-time gate

`quality` measures the vault after the fact. `page-check` keeps an avoidable defect out of it in
the first place: an agent composes the proposed page in a temporary file, checks it, and only then
writes to the vault.

```bash
graph-wiki page-check --path concepts/rate-limiting.md --content /tmp/page.md --json
graph-wiki page-check @research --path concepts/rate-limiting.md --from-stdin --json
graph-wiki page-check --path concepts/rate-limiting.md --content /tmp/page.md --mode create
```

The gate combines three checks:

1. **Contract.** The same required frontmatter as `validate`, including a `provenance` block and
   a summary within 200 characters.
2. **Path.** The target must be a safe vault-relative `.md` inside a declared content root, not a
   reserved special file or system area.
3. **Canonical identity.** Duplicate normalized titles and aliases are warnings; slug collisions
   and similar titles or summaries are soft candidates for a merge.

`fail` blocks the write (`invalid_page`, `invalid_target`, `target_exists` on create,
`target_missing` on update). `warn` requires a decision: merge into the reported page, retarget an
update, or record why a separate page is genuinely distinct. `--strict` turns duplicate warnings
into a non-zero exit for automation.

The lightweight `wiki-ingest` path and direct writes in the recoverable packet integration call
this gate before replacing a live page. Staged artifacts are reviewed by a human before promotion;
wiring the same gate into that promotion step is the next integration point.

## Review SLA

A reviewed page does not stay reviewed forever. The report derives a due date from the lifecycle,
the human-reviewed confidence, and the trust ledger's `reviewed_at` timestamp:

| Lifecycle | Base interval at confidence 0.5 |
|---|---|
| `draft` | 30 days |
| `reviewed` | 180 days |
| `verified` | 365 days |
| `disputed` | 14 days |

The effective interval is `max(7, round(base × (0.5 + confidence)))`: strong evidence buys a longer
review window, weak evidence shortens it. Pages within 14 days of the due date are `due_soon`;
past it they are `overdue`. `archived` pages and pages without a ledger entry are not scheduled —
the trust dimension already reports unreviewed pages.

The results appear as `findings.review_overdue`, `findings.review_due_soon`, and
`metrics.review.{tracked,overdue,due_soon}`. An overdue review makes the freshness dimension warn.

## Contradiction register and duplicate candidates

The consistency dimension exposes two deterministic registers:

- **Contradictions** — every explicit `contradicts` or `disputes` relationship edge, plus pages
  whose lifecycle is `disputed`. This is a register of disagreements the vault already records,
  not an LLM claim that two passages conflict. Semantic detection stays in the `wiki-lint`
  workflow.
- **Duplicate candidates** — page pairs with the same normalized title, a title/alias collision, or
  a highly similar title. They are merge candidates for `wiki-dedup`, not proof that two pages must
  be merged.

Both are informational signals: they appear in `findings` and in `metrics`, but they do not
automatically fail the quality gate.

## Quality delta

Daily maintenance should report what changed, not just the current state. Pass a previous snapshot
to get a deterministic delta:

```bash
state="$HOME/.graph-wiki/state/<vault-id>"
graph-wiki quality "$VAULT" \
  --baseline "$state/quality-latest.json" \
  --save "$state/quality-latest.json" \
  --json > quality-report.json
```

`--baseline` reads the previous report; `--save` atomically writes the current report (without the
transient delta block) for the next run. The embedded `delta` block contains:

- `status`: `first_run`, `stable`, `improved`, or `regressed`;
- `status_change` and `dimension_changes`;
- count deltas for pages, tokens, findings, reviews, contradictions, and candidates;
- `new_findings` / `resolved_findings`, keyed by finding category;
- `totals.new` and `totals.resolved`.

A new warning or failure with nothing resolved marks the run `regressed`; fixing findings without
new ones marks it `improved`. The snapshot must live outside the vault — `--save` rejects a path
inside it — so the command remains read-only with respect to knowledge pages.

The `daily-update` workflow runs this comparison after its index and hot-cache work, writes
`quality-report.json`, `quality-delta.json`, and `quality-delta.md` to the invocation artifacts, and
records new review failures, contradictions, and duplicate candidates in the completion report.

## Severity policy

| Dimension | Fails when | Warns when |
|---|---|---|
| Structure | broken link or missing core frontmatter | missing summary, page above the token ceiling |
| Traceability | — | missing sources, missing/invalid provenance block, provenance drift |
| Consistency | — | duplicate title groups, orphan pages, relationship issues |
| Coverage | manifest entry with no pages, or a phantom page | — |
| Freshness | — | missing lifecycle, stale material fingerprint, overdue review |
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
- `--strict`, `--strict-trust`, and `--require-trust-ledger` gate modes;
- the `page-check` pre-write gate for contract and canonical identity;
- lifecycle/confidence review SLAs with overdue and due-soon findings;
- a deterministic contradiction register and duplicate-candidate report;
- `--baseline` / `--save` quality deltas and their `daily-update` integration.

Planned next:

- citation-locator resolution (source path plus line or anchor);
- the same pre-write gate for staged promotion;
- semantic contradiction detection shared with the `wiki-lint` workflow;
- answer-grounding evaluation alongside retrieval metrics;
- per-vault threshold overrides and long-horizon trend dashboards.

`quality` is a gate, not a grade. It is designed to stop known-bad states and surface missing
evidence, not to declare that a page is correct.
