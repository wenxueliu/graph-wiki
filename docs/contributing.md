English | [简体中文](contributing.zh-CN.md)

# Contributing

This is early. The skills work, but there's room to make the brain smarter: better cross-referencing, sharper deduplication, bigger vaults, new ingest sources. If you've been chewing on this problem or have a workflow that could be a skill, PRs are welcome.

## Adding a new skill

1. Create a folder in `.skills/your-skill-name/`
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown instructions
3. Run `obsidian-wiki setup` in the project to link it into the selected agent directories
4. Test by saying something to your agent that matches the description

The `description` is load-bearing — it's the only thing an agent sees when deciding whether your skill is relevant. Write it as a list of the phrases a user would actually say, and state what the skill is *not* for when it's easily confused with a neighbour.

See [`.skills/skill-creator/SKILL.md`](../.skills/skill-creator/SKILL.md) for the full guide, or just ask your agent to run `/skill-creator`.

When you add a skill, also add it to the [skills reference](skills.md) and the routing table in `AGENTS.md`.

### Workflow-backed skills

A top-level `workflows/*.yaml` is the authoritative execution contract for its same-named Agent Skill. After changing a workflow, synchronize and check `.skills/<name>/SKILL.md`:

```bash
python tools/sync_workflow_skills.py
python tools/sync_workflow_skills.py --check
```

The generator deterministically renders the workflow's `do`, `input`, `output`, `check`, and control-flow fields into Agent Skill markdown instructions; it never hands raw YAML to the agent runtime. Do not hand-edit the generated `SKILL.md` — land behavior changes in the workflow first.

## Adding a Knowledge Pack

A directory under `knowledge-packs/<name>/` is a complete Knowledge Pack, not only a folder
template. It must contain:

```text
profile.json          # semantic purpose, scope, knowledge and trust contract
layout.json           # pack identity and references to profile/routing contracts
routing.json          # deterministic page-type-to-path rules
routing.md            # semantic placement guidance
vault/                # missing-only schema, rules, terminology and directory template
```

Keep the boundary explicit:

- Put purpose, include/exclude scope, durable knowledge types, extraction retain/omit rules,
  authorities, checks, freshness triggers, and retrieval priorities in `profile.json`.
- Put content roots, system areas, placeholders, and path templates in the routing/Layout files.
- Put domain page validation in the vault schema. Do not use a directory name as a substitute for
  a knowledge-type definition.

The Profile `name` must match the pack/Layout name, every `knowledge_types` entry must have a
declared route, and a scope mismatch must choose `ask`, `stage`, or `reject`; Profiles never switch
the target domain automatically. Add loader, marker, context-resolution, and focused tests when the
contract shape changes.

## Keeping the translations in sync

The project ships documentation in exactly two languages: English (`.md`) and Simplified Chinese
(`.zh-CN.md`). `README.md` / `README_ZH.md` are the root pair; every page under `docs/` has an
English `<name>.md` and a Simplified Chinese `<name>.zh-CN.md` mirror.

Each pair is **one documentation surface**. Keep headings, examples, links, commands, numbers, and
user-facing behavior aligned. Add no other languages — Traditional Chinese and every other locale
are out of scope.

Every English page opens with a switcher line and its mirror links back:

```markdown
English | [简体中文](<name>.zh-CN.md)          <!-- docs/<name>.md -->
[English](<name>.md) | 简体中文                 <!-- docs/<name>.zh-CN.md -->
```

`tests/test_docs_language_policy.py` enforces the mirror set, the switcher lines, and the absence of
`zh-TW`/other locale files. README drift is reported, not gated, by the `readme-translation-drift`
CI job:

```bash
python tools/check_readme_sync.py
```

For each translation, that tool lists the commits that changed `README.md` without a later update to
that translation, plus the pending English diff. Translate and backfill those into each translation
file. Reviewers assess translation quality.

## Repo conventions

- `.skills/` is the source of truth. Project targets such as `.claude/skills/` and `.agents/skills/` are links created by `obsidian-wiki setup`; legacy global targets such as `~/.codex/skills/` may be created by `python3 setup.py`. Never edit a linked copy.
- `CLAUDE.md`, `GEMINI.md`, and `.hermes.md` are symlinks to `AGENTS.md`. Edit `AGENTS.md`.
- New config variables belong in three places: `.env.example`, [`docs/configuration.md`](configuration.md), and the skill that reads them.
- New CLI subcommands belong in [`docs/cli.md`](cli.md).
- New user-facing skills belong in [`docs/skills.md`](skills.md) and the routing table in `AGENTS.md`.

## Tests

```bash
pytest
```

Tests live in `tests/`. Skill behavior that can be asserted deterministically (config resolution, manifest handling, graph math, session indexing) has coverage there; the LLM-driven parts don't.
