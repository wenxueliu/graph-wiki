English | [简体中文](agents.zh-CN.md)

# Agent Compatibility

Works with **any AI coding agent that can read files**. `graph-wiki setup` offers explicit agent
targets (`--list-agents`, then one or more `--agent NAME` selections); `python3 setup.py` delegates
to the same installer with `--agent all`, so a source checkout gets every project-local target.

Each agent has its own convention for discovering skills. `graph-wiki setup` installs only below
the command directory: native project paths where available, and the shared `.agents/skills/`
project path for agents that previously had only global targets. It never writes skill files under the user's home directory.

## Matrix

| Agent | Bootstrap | Skills Directory | Slash Commands |
|---|---|---|---|
| **[Claude Code](https://claude.ai/code)** | `CLAUDE.md` | `.claude/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-status`, etc. |
| **[Cursor](https://cursor.com)** | `.cursor/rules/graph-wiki.mdc` | `.cursor/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-status`, etc. |
| **[Windsurf](https://windsurf.com)** | `.windsurf/rules/graph-wiki.md` | `.windsurf/skills/` | ✅ via Cascade |
| **[Codex (OpenAI)](https://openai.com/codex)** | `AGENTS.md` | `.agents/skills/` | `$wiki-folder-ingest` (Codex uses `$`) |
| **[Gemini CLI](https://github.com/google-gemini/gemini-cli)** | `GEMINI.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-query`, etc. |
| **[Google Antigravity](https://antigravity.google)** | `.agent/rules/` + `.agent/workflows/` | `.agents/skills/` | ✅ via workflows registry |
| **[Kiro IDE/CLI](https://kiro.dev)** | `.kiro/steering/graph-wiki.md` | `.kiro/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-status`, etc. |
| **[Hermes](https://hermes-agent.nousresearch.com)** | `.hermes.md` | `.agents/skills/` | ✅ `/hermes-history-ingest`, `/wiki-agent hermes <topic>` |
| **[OpenClaw](https://openclaw.ai)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-history-ingest openclaw`, etc. |
| **[OpenCode](https://opencode.ai)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-query`, etc. |
| **[Aider](https://aider.chat)** | `AGENTS.md` | `.agents/skills/` | Describe intent in chat |
| **[Factory Droid](https://factory.ai)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-query`, etc. |
| **[Trae](https://trae.ai)** / **Trae CN** | `AGENTS.md` | `.agents/skills/` | ✅ via Agent tool |
| **GitHub Copilot (VS Code)** | `.github/copilot-instructions.md` | — | Describe intent in chat |
| **GitHub Copilot (CLI)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-query`, etc. |
| **[Kilocode](https://kilo.ai/)** | `AGENTS.md` / `CLAUDE.md` | `.agents/skills/` + `.claude/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-status`, etc. |
| **[Pi](https://pi.dev)** | `AGENTS.md` | `.pi/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-history-ingest pi`, etc. |
| **CodeAgent** | `AGENTS.md` | `.cac/skills/` | ✅ `/wiki-folder-ingest`, `/wiki-status`, etc. |

> Slash commands work in Claude Code, Cursor, Windsurf, and most CLI agents. Everywhere else, just describe what you want — the agent matches your intent against the skill descriptions.

Named-vault routing (`@work update wiki`) works in every agent above, because `@name` is documented in the shared skills and bootstrap context that all of them load.

## Manual setup

Only needed if you're not running `python3 setup.py` or `graph-wiki setup`.

<details>
<summary><b>Claude Code</b></summary>

Skills are auto-discovered from `.claude/skills/`. Either run `python3 setup.py` or copy `.skills/*` to `.claude/skills/`. The `CLAUDE.md` file at the repo root is automatically loaded as project context.

```bash
cd /path/to/graph-wiki && claude "set up my wiki"
```
</details>

<details>
<summary><b>Cursor</b></summary>

Skills are auto-discovered from `.cursor/skills/`. The `.cursor/rules/graph-wiki.mdc` file provides always-on context. Either run `python3 setup.py` or copy `.skills/*` to `.cursor/skills/`. Then type `/wiki-setup` in the chat.
</details>

<details>
<summary><b>Windsurf</b></summary>

Cascade reads rules from `.windsurf/rules/` and skills from `.windsurf/skills/`. Either run `python3 setup.py` or copy `.skills/*` to `.windsurf/skills/`. Then tell Cascade: "set up my wiki".
</details>

<details>
<summary><b>Codex</b></summary>

Reads `AGENTS.md` for project context. Skills are discovered from the shared project path
`.agents/skills/`. Either run `python3 setup.py` or manually symlink `.skills/*` to `.agents/skills/`.

```bash
cd /path/to/graph-wiki && codex "set up my wiki"
```
</details>

<details>
<summary><b>Gemini CLI</b></summary>

Reads `GEMINI.md` and discovers skills from the shared project path `.agents/skills/`. Either run
`python3 setup.py` or manually symlink `.skills/*` to `.agents/skills/`.

```bash
cd /path/to/graph-wiki && gemini "set up my wiki"
```
</details>

<details>
<summary><b>Google Antigravity</b></summary>

Always-on via `.agent/rules/` + `.agent/workflows/`. `python3 setup.py` ships both files and symlinks
skills into the project-local `.agents/skills/`.
</details>

<details>
<summary><b>Kiro IDE/CLI</b></summary>

Always-on via `.kiro/steering/*.md` with `inclusion: always`. `python3 setup.py` symlinks `.skills/*`
into the project-local `.kiro/skills/`. Invoke with `/wiki-folder-ingest`, `/wiki-query`, etc.
</details>

<details>
<summary><b>OpenCode / Aider / Factory Droid / Trae</b></summary>

All read `AGENTS.md` at the repo root. `python3 setup.py` symlinks skills into the project-local
`.agents/skills/` (shared discovery path). Trae and Trae CN use the same project-local path.
</details>

<details>
<summary><b>Hermes</b></summary>

Reads `.hermes.md` first, then falls back to `AGENTS.md`. Project-local skills live in
`.agents/skills/`.

```bash
cd /path/to/graph-wiki && hermes "set up my wiki"
# Bulk-ingest ~/.hermes memories and sessions:
/hermes-history-ingest
# Pull Hermes knowledge on one topic into the vault:
/wiki-agent hermes <topic>
```

`hermes-history-ingest` mirrors the other bulk history skills: it reads `~/.hermes` (or
`$HERMES_HOME`), merges memories and sessions by topic, and honors `.manifest.json` for incremental
runs. Use `/wiki-agent hermes <topic>` when you only need one question answered.
</details>

<details>
<summary><b>OpenClaw</b></summary>

Reads `AGENTS.md` (priority 10). Discovers project-local skills from `.agents/skills/`. Skills
auto-register as slash commands.

```bash
cd /path/to/graph-wiki && openclaw "set up my wiki"
# Mine OpenClaw history:
/wiki-history-ingest openclaw
```
</details>

<details>
<summary><b>GitHub Copilot</b></summary>

**VS Code Chat:** reads `.github/copilot-instructions.md`. Say "set up my wiki" in Copilot Chat.

**CLI:** discovers project-local skills from `.agents/skills/`. Run `python3 setup.py` or manually
symlink `.skills/*` there.
</details>

<details>
<summary><b>Pi</b></summary>

Reads `AGENTS.md` (walking up from cwd). Discovers project-local skills from `.pi/skills/` and
`.agents/skills/`. Run `python3 setup.py` or manually symlink `.skills/*` to `.pi/skills/`.

```bash
cd /path/to/graph-wiki && pi "set up my wiki"
# Mine Pi session history:
/wiki-history-ingest pi
```
</details>

<details>
<summary><b>CodeAgent</b></summary>

Reads `AGENTS.md` for project context. Discovers skills from `.cac/skills/`. Run `graph-wiki setup --agent codeagent` or manually symlink `.skills/*` to `.cac/skills/`.
</details>
