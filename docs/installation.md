English | [简体中文](installation.zh-CN.md)

# Installation

Four ways in. Pick one — they all end at the same place: your vault path in the config file (`<project>/.graph-wiki/config` for setup-created projects; `~/.graph-wiki/config` when unset) and the skills discoverable by your agent.

| Path | Best for | Writes config | Agent skill targets |
|---|---|---|---|
| [pip](#install-via-pip-recommended) | Most people | ✅ | User-selected, command-directory only |
| [Let your agent do it](#let-your-agent-set-it-up) | No terminal required | ✅ | Current agent |
| [git clone + `python3 setup.py`](#install-via-git-clone) | Contributors, hackers | ✅ | Project-local all-agent installer |
| [Skills CLI](#install-via-skills-cli-deprecated) | Deprecated — partial install | ❌ | Current agent only |

## Install via pip (recommended)

```bash
pip install graph-wiki-skills
graph-wiki setup --vault /path/to/your/digital/brain
```

`graph-wiki setup` writes the config to `<project>/.graph-wiki/config` by default (the shipped
`.env.example` sets `GRAPH_WIKI_CONFIG_DIR=.graph-wiki`; leave it empty for `~/.graph-wiki`) and asks
which agent skill targets to install. It has no implicit all-agent selection and never installs skills globally.
Skills and bootstrap files are written only under the directory where the command runs (or the
explicit `--project DIR` override). Skills are symlinked to the installed package, so
`pip install -U graph-wiki-skills` upgrades the selected targets when setup is run again.

For scripts and other non-interactive environments, select targets explicitly:

```bash
graph-wiki setup --vault /path/to/brain --knowledge-pack default --agent claude --agent codex
graph-wiki setup --vault /path/to/brain --knowledge-pack software-knowledge --agent claude,codex,pi
graph-wiki setup --vault /path/to/brain --knowledge-pack default --agent all
```

Run `graph-wiki setup --list-agents` to see the stable project-local target names. Non-interactive setup requires an explicit selection; use `--agent none`
only when intentionally configuring the vault without installing agent skills.

If `--knowledge-pack` is omitted in a terminal, setup displays the available Knowledge Packs and requires
one selection. Agent selection accepts multiple values; Knowledge Pack selection is always single-choice.
Non-interactive setup must pass `--knowledge-pack NAME` explicitly.

Then open that directory in your agent and say **"set up my wiki"**.

Useful flags:

```bash
graph-wiki setup --project /work/app  # override the command-directory target
graph-wiki setup --copy        # copy skill files instead of symlinking
```

For a self-contained project installation using the `software-knowledge` Pack, run:

```bash
graph-wiki setup --knowledge-pack software-knowledge --copy --agent cursor
```

This selects the `software-knowledge` Knowledge Pack, initializes the configured vault, and
installs the selected agent's project-local skills and bootstrap files, plus a missing `.env` from the packaged template
under the command directory. The deprecated `--project-only` flag is retained as a no-op for compatibility because
CLI setup no longer has any global skill-install phase. `--copy` stores
independent skill files instead of symlinks, which is useful when the project must remain
self-contained.

The project `.env` is created only when it does not already exist; setup never overwrites an
existing project configuration. When `--vault` is supplied, its resolved absolute path is
written to `OBSIDIAN_VAULT_PATH` in the new `.env`. Setup also fills the stable context bindings
declared by `.env.example`: the Knowledge Pack, owner/Writing Profile paths, vault metadata and
taxonomy paths, and the persistent compiled-context snapshot path. Existing `.env` files remain
preserved except that setup fills missing or blank stable-binding keys; non-empty custom values,
unknown fields, and comments are retained. Run setup/repair after changing these bindings.

`OBSIDIAN_VAULT_PATH` is just any directory where you want your digital brain to live — a new empty folder or an existing Obsidian vault. In an interactive terminal, omit `--vault` to enter the folder; the displayed default is the current directory, accepted by pressing Enter. In a non-interactive run, pass `--vault` explicitly or use the existing value in the config file (setup-created projects default to `<project>/.graph-wiki/config`; otherwise `~/.graph-wiki/config`).

The agent selection also filters generated project rules and entry files. Selecting only Claude,
for example, creates shared `AGENTS.md`, `CLAUDE.md`, and `.claude/skills/`, without generating
the files for other agents. Selecting several agents generates the union of their files.

Run `graph-wiki info` to see the resolved paths and `graph-wiki doctor` to health-check the result. See the [CLI reference](cli.md) for everything else the package ships.

## Let your agent set it up

The fastest path — no commands required. Give your agent this repo and say:

```text
https://github.com/wenxueliu/graph-wiki — set up my wiki
```

The agent reads [`.skills/wiki-setup/SKILL.md`](../.skills/wiki-setup/SKILL.md) from the repo, asks where you want your vault to live, and initializes the full structure: directories, index, log, Obsidian config, and an optional auto-capture hook. The skill *is* the setup guide.

This works in any agent that can read files (Claude Code, Cursor, Windsurf, Codex, Gemini CLI, Kiro, and more). After setup, every wiki skill is available immediately.

## Install via git clone

```bash
git clone https://github.com/wenxueliu/graph-wiki.git
cd graph-wiki
python3 setup.py
```

`python3 setup.py` asks for your vault path and then delegates to the installed CLI with
`graph-wiki setup --agent all`. The config goes to `<project>/.graph-wiki/config` by default
(the shipped `.env.example` sets `GRAPH_WIKI_CONFIG_DIR=.graph-wiki`), and skills are installed
into the project only (copy mode on Windows, symlinks on Unix). Nothing is written to global
agent directories.

Open the project in your agent and say **"set up my wiki"**.

For local-only config, copy `.env.example` to `.env` and set `OBSIDIAN_VAULT_PATH`. A `.env` in the
working directory (or any parent up to `$HOME`) takes precedence over the config file. The template
already sets `GRAPH_WIKI_CONFIG_DIR=.graph-wiki`, so a copied `.env` keeps the entire configuration
inside the project; leave that value empty to use `~/.graph-wiki`. Every vault-aware command (`query`, `context-pack`,
`lint`, `trust-*`, `validate`, `verify`, `doctor`, `sync`) then reads the project's `.env`, and
`@name` profiles resolve from `<project>/.graph-wiki/config.<name>`. See
[Configuration](configuration.md#keeping-configuration-inside-a-project).

### What `python3 setup.py` wires up

`python3 setup.py` is a thin shim over the packaged CLI: it runs
`graph-wiki setup --agent all` from the checkout, so source and pip/uv installs share one
implementation. It writes:

1. **Config** at `<project>/.graph-wiki/config` by default (the shipped `.env.example` sets `GRAPH_WIKI_CONFIG_DIR=.graph-wiki`; leave it empty for `~/.graph-wiki`) with your vault path and the repo location. This is how skills know where to read and write.
2. **Project-local skill mirrors** — symlinks (or copies with `--copy`) at `.claude/skills/`, `.cursor/skills/`, `.windsurf/skills/`, `.pi/skills/`, `.cac/skills/`, `.kiro/skills/`, plus an always-copied shared `.agents/skills/`
3. **Always-on rule files** — `CLAUDE.md`, `GEMINI.md`, `AGENTS.md`, `.hermes.md`, `.cursor/rules/…`, `.windsurf/rules/…`, `.kiro/steering/…`, `.agent/rules/…`, `.agent/workflows/…`, `.github/copilot-instructions.md`
4. **GitHub sync** (optional) — see [Configuration → Syncing your vault to GitHub](configuration.md#syncing-your-vault-to-github)

No skills are written under `~/.claude/skills`, `~/.codex/skills`, or any other user-home
directory. `graph-wiki setup` installs only the agents you select; `setup.py` passes
`--agent all`, which means "every agent in this project", not "every agent globally".

## Install via Skills CLI (deprecated)

```bash
npx skills add wenxueliu/graph-wiki
```

This only installs the markdown skills into the current agent. It does **not** write the config file (`.graph-wiki/config` or `~/.graph-wiki/config`), configure GitHub sync, or wire the project bootstrap that `graph-wiki setup` performs. The `python3 setup.py` source installer delegates to `graph-wiki setup --agent all` and remains project-local.

Use this path only if you intentionally want a partial, agent-local install and are prepared to manage config yourself. For a complete setup, use pip or git clone instead.

Browse the full skill list at [skills.sh/wenxueliu/graph-wiki](https://skills.sh/wenxueliu/graph-wiki).

## Open in Obsidian

Open your vault directory in Obsidian (File → Open Vault). The wiki pages, wikilinks, and graph view all work natively. Nothing about the vault is proprietary — it's markdown files with YAML frontmatter.

## Multiple vaults

Keep a default vault in the config file (setup-created projects: `<project>/.graph-wiki/config`; otherwise `~/.graph-wiki/config`), or create named configs by copying it to `<config-dir>/config.work` and changing `OBSIDIAN_VAULT_PATH`.

Profiles can also live inside a project. A `.env` created from the shipped template already sets
`GRAPH_WIKI_CONFIG_DIR=.graph-wiki`, keeping `config`, `config.<name>`, and `WRITING.md` there —
nothing is read from or written to `~/.graph-wiki`. Use this when one repository owns one vault and several repositories
must stay independent. `@name` and the plain default both resolve inside that directory.

Each profile points at a separate vault directory, and Obsidian treats those as independent vaults:
open one at a time (or one per window). Obsidian has no cross-vault links, no merged graph, and no
shared index, so nothing under `@work` links to or is retrievable from `@personal`, and one
`wiki-query` call reads one vault. Keep a single vault unless the knowledge genuinely serves a
different purpose.

From any directory, route one request to a named vault with `@name`:

```text
@work update wiki
@research save this
wiki-query @personal what do I know about MCP security
```

The `@name` override applies **only to that request** and never changes your default vault. To change the default, re-run `graph-wiki setup --vault <path>`, or copy the profile you want over the active `config` file.

All supported agents can use this syntax after `graph-wiki setup` or `python3 setup.py`, because the shared skills and always-on bootstrap files all point back to the same Config Resolution Protocol. Claude Code, Cursor, Windsurf, Codex, Gemini, Kiro, Hermes, OpenClaw, Copilot CLI, Pi, and the generic `AGENTS.md` agents all pick it up from the same instructions.

The routing token works with write skills (`@work update wiki`, `@research save this`) and read skills (`wiki-query @personal what do I know about X`).

## Verifying the install

```bash
graph-wiki doctor
```

`doctor` catches broken setup, stale installs, and malformed vault state. Add `--json` for machine-readable output.

## Next steps

- [Skills Reference](skills.md) — what you can actually ask for
- [Configuration](configuration.md) — every config variable, QMD, GitHub sync
- [Agent Compatibility](agents.md) — per-agent details and manual setup
