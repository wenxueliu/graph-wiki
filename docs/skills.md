English | [简体中文](skills.zh-CN.md)

# Skills Reference

Everything lives in [`.skills/`](../.skills/) — **50 skills**, each a folder with a `SKILL.md` the
agent reads when your request matches its description. There is no runtime, no plugin system, and no
registration step.

Slash commands (`/skill-name`) work in Claude Code, Cursor, Windsurf, and most CLI agents. Everywhere
else, just describe what you want.

Skills marked **internal** are invoked only by the parent skill that owns their input contract; do not
call them directly.

## Setup & vaults

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-setup` | Initialize or safely repair the vault's config, Knowledge Pack, core files, and optional integrations | `/wiki-setup` |
| `wiki-switch` | Manage multiple named vault profiles and switch the active one | `/wiki-switch <name>` |
| `daily-update` | Vault-scoped daily maintenance: source freshness, index, hot cache, state files, independent verification, log | `/daily-update` |
| `daily-update-setup` | Install or verify the daily 09:00 schedule, vault-scoped state, and optional terminal reminder after approval | `/daily-update-setup` |
| `wiki-context` | internal — resolve the vault from config and build the shared runtime context every other skill reads | — |
| `wiki-setup-contract` | internal — render the hashed core setup contract from workflow-local templates, then merge optional integration and acceptance contracts | — |
| `wiki-page-contract` | internal — compile the shared wiki context plus the transaction scope into an immutable effective page-write contract | — |
| `wiki-finalize-sources` | internal — update special files once the exact-hash source completion gate holds, and commit one or more sources manifest-last | — |

## Feeding the brain

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-folder-ingest` | Recoverable text ingest: discover and plan local sources, inline-extract small documents, extract large documents into isolated Packets, and integrate them serially in source/unit order | `/wiki-folder-ingest` |
| `wiki-ingest` | Lightweight text ingest: normalize each file into independent Ingest Documents and merge them directly in fresh sessions — no Job, no Packet, no `claude -p` | `/wiki-ingest` |
| `wiki-ingest-document` | internal — integrate one planned Ingest Document and record completion in `.manifest.json` | — |
| `wiki-source-text` | internal — extract one coordinator-assigned UTF-8 range into a validated Packet | — |
| `wiki-packet-integrate` | internal — validate and serially integrate one Packet using the frozen Job context and page contract | — |
| `wiki-capture` | Save the current conversation as a structured wiki note; `--quick` stages findings to `_raw/` in under 60 seconds | `/wiki-capture` |
| `wiki-update` | Incrementally distill architecture decisions and reusable knowledge from the project you're standing in | `/wiki-update` |
| `wiki-research` | Autonomous multi-round web research, synthesized and filed straight into the vault | `/wiki-research [topic]` |
| `wiki-history-ingest` | Router for bulk agent-history ingest | `/wiki-history-ingest <agent>` |
| `claude-history-ingest` | Mine Claude CLI and Desktop sessions into traceable wiki knowledge | `/claude-history-ingest` |
| `codex-history-ingest` | Mine `~/.codex` sessions and rollout logs | `/codex-history-ingest` |
| `hermes-history-ingest` | Mine `~/.hermes` memories and session transcripts | `/hermes-history-ingest` |
| `copilot-history-ingest` | Mine GitHub Copilot CLI sessions (`~/.copilot/session-state`) | `/copilot-history-ingest` |
| `openclaw-history-ingest` | Mine `~/.openclaw` `MEMORY.md` and sessions | `/openclaw-history-ingest` |
| `pi-history-ingest` | Mine `~/.pi/agent/sessions` JSONL history | `/pi-history-ingest` |
| `wiki-agent` | Topic-first ingest from one agent's raw history, returning a synthesized answer for the current session | `/wiki-claude`, `/wiki-codex`, `/wiki-hermes`, `/wiki-openclaw`, `/wiki-copilot`, `/wiki-pi` |

`wiki-history-ingest` routes `claude`, `copilot`, `codex`, `hermes`, `openclaw`, and `pi` for bulk
history. `/wiki-hermes <topic>` remains the topic-targeted alternative: it ingests only the Hermes
sessions relevant to one question and returns a synthesized answer through `wiki-agent`.

Text ingest V1 accepts UTF-8 `.md`, `.markdown`, `.mdx`, `.txt`, and `.rst` only. PDFs, Office
documents, structured data, logs/transcripts, HTML/URLs, media, archives, and source code are
reported explicitly rather than treated as generic text. Agent histories and web research keep their
dedicated skills above.

## Asking the brain

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-query` | Read-only answers from the compiled wiki with citations — GraphRAG, index, QMD, local bodies, then multi-hop typed graph | `/wiki-query` |
| `wiki-narrate` | Render a cited briefing, plain-language explanation, or progressive lecture from a topic | `/wiki-narrate <topic>` |
| `wiki-digest` | Newsletter-style summary of what you learned over a day, week, or month | `/wiki-digest [period]` |
| `wiki-context-pack` | Produce a token-bounded, citation-ready context slice for a downstream agent or task | `/wiki-context-pack` |
| `memory-bridge` | Browse and diff already-compiled knowledge by which AI tool produced it | `/memory-bridge` |

## Finding past sessions

These two build a retrieval index over your raw agent sessions. They write a sidecar under
`~/.claude/session-brain/` (override with `WIKI_SESSION_BRAIN_DIR`) and **never touch the vault**. See
[Session Brain](session-brain.md).

| Skill | What it does | Slash command |
|---|---|---|
| `session-brain` | Build and maintain a topic graph over your agent session history | `/session-brain` |
| `session-search` | Find a past session by topic and load its context into the current conversation | `/wiki-sessions <topic>` |

> **Ingest vs. retrieve.** If you want knowledge preserved as permanent vault pages, use
> `wiki-history-ingest`. If you want to find the session where something happened, use these.

## Maintaining the brain

| Skill | What it does | Slash command |
|---|---|---|
| `wiki-status` | Read-only source delta, health priorities, and token footprint — plus optional vault-shape insights | `/wiki-status` |
| `wiki-lint` | Read-only audit of structure, schema, links, provenance, and graph health, with a reviewable report | `/wiki-lint` |
| `wiki-lint-consolidate` | Full lint dry-run, then — after human approval — apply the automatable structural maintenance | `/wiki-lint-consolidate` |
| `wiki-dedup` | Identity resolution — merge pages covering the same concept under different names | `/wiki-dedup` |
| `cross-linker` | Discover and write high-confidence page links, typed relationships, and misc affinity | `/cross-linker` |
| `obsidian-vault-linker` | Discover and write typed relationships between vault notes using plain Markdown and YAML — no plugins required | `/obsidian-vault-linker` |
| `tag-taxonomy` | Audit, normalize, or extend the controlled tag vocabulary, maintaining tracking and the optional QMD index | `/tag-taxonomy` |
| `wiki-synthesize` | Discover concept clusters that co-occur but have no synthesis page, and fill the gap | `/wiki-synthesize` |
| `wiki-stage-commit` | Promote staged pages or patches to live content after per-item human approval | `/wiki-stage-commit` |
| `wiki-rebuild` | Archive first, then snapshot, prepare a clean rebuild, or restore a previous archive | `/wiki-rebuild` |

## Seeing & moving the brain

| Skill | What it does | Slash command |
|---|---|---|
| `graph-colorize` | Color-code the Obsidian graph view by tag, category, or visibility | `/graph-colorize` |
| `wiki-dashboard` | Create dynamic Obsidian Bases or Dataview dashboards | `/wiki-dashboard` |
| `wiki-export` | Export the graph to JSON, GraphML, Neo4j Cypher, interactive HTML, or an OKF bundle | `/wiki-export` |
| `wiki-import` | Import a `graph.json` export (stubs) or an OKF markdown bundle (full bodies) into the current vault | `/wiki-import` |
| `obsidian-layout-adjustment` | Restyle Obsidian with CSS snippets — tabs, sidebars, graph panes, note surfaces | `/obsidian-layout-adjustment` |

## Extending the framework

| Skill | What it does | Slash command |
|---|---|---|
| `llm-wiki` | The core pattern and architecture reference every other skill defers to | `/llm-wiki` |
| `skill-creator` | Create, edit, and eval new skills | `/skill-creator` |
| `vault-skill-factory` | Turn a cluster of mature vault pages into a portable "digital expert" skill | `/vault-skill-factory` |
| `impl-validator` | Validate an implementation against its stated goal, with a reviewable PASS/WARN/FAIL verdict | `/impl-validator` |

## Example skill sets

[`example/design/`](../example/design/) contains a self-contained single-product design example
with a project `AGENTS.md` and five sample Agent Skills for requirements, design, implementation
planning, test design, and issue diagnosis. These examples consume the `software-knowledge` Pack
but are not installed as framework skills.

## Recommended companion: Obsidian Skills by Kepano

This framework handles the knowledge-management workflow — ingest, query, lint, rebuild. For Obsidian
format mastery, install [**kepano/obsidian-skills**](https://github.com/kepano/obsidian-skills)
alongside it. Optional, but it improves output quality:

| Skill | What it adds |
|---|---|
| `obsidian-markdown` | Correct Obsidian-flavored syntax — wikilinks, callouts, embeds, properties |
| `obsidian-bases` | Create and edit `.base` files (database-like views of notes) |
| `json-canvas` | Create and edit `.canvas` files (visual mind maps, flowcharts) |
| `obsidian-cli` | Interact with a running Obsidian instance via CLI |
| `defuddle` | Extract clean markdown from web pages — less noise, fewer tokens during ingest |

```bash
npx skills add kepano/obsidian-skills
```

Both projects follow the same [Agent Skills spec](https://agentskills.io/specification), so they coexist in the same `.skills/` directory with no conflicts.

## Writing your own

See [Contributing → Adding a new skill](contributing.md#adding-a-new-skill), or just ask:

> "Create a skill that generates weekly summaries from my journal entries"

`skill-creator` walks you through drafting, testing, and refining it in `.skills/`.
