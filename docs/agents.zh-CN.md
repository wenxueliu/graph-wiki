[English](agents.md) | 简体中文

# Agent 兼容性

适用于 **任何能读取文件的 AI 编程 agent**。`graph-wiki setup` 提供显式的 agent 目标
（`--list-agents`，然后一个或多个 `--agent NAME` 选择）；`python3 setup.py` 委托给同一个安装器并
传入 `--agent all`，因此源码 checkout 会得到全部项目本地目标。

每个 agent 有自己的 skill 发现约定。`graph-wiki setup` 只安装在命令所在目录之下：能用原生项目路径
的用原生路径，其余此前只有全局目标的 agent 使用共享的 `.agents/skills/` 项目路径。它从不把 skill 文件
写进用户主目录。

## 对照表

| Agent | Bootstrap | Skills 目录 | Slash command |
|---|---|---|---|
| **[Claude Code](https://claude.ai/code)** | `CLAUDE.md` | `.claude/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-status` 等 |
| **[Cursor](https://cursor.com)** | `.cursor/rules/graph-wiki.mdc` | `.cursor/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-status` 等 |
| **[Windsurf](https://windsurf.com)** | `.windsurf/rules/graph-wiki.md` | `.windsurf/skills/` | ✅ 通过 Cascade |
| **[Codex (OpenAI)](https://openai.com/codex)** | `AGENTS.md` | `.agents/skills/` | `$wiki-folder-ingest`（Codex 用 `$`） |
| **[Gemini CLI](https://github.com/google-gemini/gemini-cli)** | `GEMINI.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-query` 等 |
| **[Google Antigravity](https://antigravity.google)** | `.agent/rules/` + `.agent/workflows/` | `.agents/skills/` | ✅ 通过 workflows registry |
| **[Kiro IDE/CLI](https://kiro.dev)** | `.kiro/steering/graph-wiki.md` | `.kiro/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-status` 等 |
| **[Hermes](https://hermes-agent.nousresearch.com)** | `.hermes.md` | `.agents/skills/` | ✅ `/hermes-history-ingest`、`/wiki-hermes <topic>` |
| **[OpenClaw](https://openclaw.ai)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-history-ingest openclaw` 等 |
| **[OpenCode](https://opencode.ai)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-query` 等 |
| **[Aider](https://aider.chat)** | `AGENTS.md` | `.agents/skills/` | 在对话中描述意图 |
| **[Factory Droid](https://factory.ai)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-query` 等 |
| **[Trae](https://trae.ai)** / **Trae CN** | `AGENTS.md` | `.agents/skills/` | ✅ 通过 Agent tool |
| **GitHub Copilot (VS Code)** | `.github/copilot-instructions.md` | — | 在对话中描述意图 |
| **GitHub Copilot (CLI)** | `AGENTS.md` | `.agents/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-query` 等 |
| **[Kilocode](https://kilo.ai/)** | `AGENTS.md` / `CLAUDE.md` | `.agents/skills/` + `.claude/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-status` 等 |
| **[Pi](https://pi.dev)** | `AGENTS.md` | `.pi/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-history-ingest pi` 等 |
| **CodeAgent** | `AGENTS.md` | `.cac/skills/` | ✅ `/wiki-folder-ingest`、`/wiki-status` 等 |

> Slash command 在 Claude Code、Cursor、Windsurf 以及多数 CLI agent 中可用。在其他 agent 中，直接描述
> 你的需求即可——agent 会把你的意图与 skill 的 description 做匹配。

命名 vault 路由（`@work update wiki`）在上表每个 agent 中都可用，因为 `@name` 记录在所有 agent 都会
加载的共享 skill 与 bootstrap 上下文中。

## 手动设置

只有在你没有运行 `python3 setup.py` 或 `graph-wiki setup` 时才需要。

<details>
<summary><b>Claude Code</b></summary>

Skill 会从 `.claude/skills/` 自动发现。运行 `python3 setup.py`，或者把 `.skills/*` 复制到
`.claude/skills/`。repo 根目录的 `CLAUDE.md` 会被自动加载为项目上下文。

```bash
cd /path/to/graph-wiki && claude "set up my wiki"
```
</details>

<details>
<summary><b>Cursor</b></summary>

Skill 会从 `.cursor/skills/` 自动发现。`.cursor/rules/graph-wiki.mdc` 提供 always-on 上下文。运行
`python3 setup.py`，或者把 `.skills/*` 复制到 `.cursor/skills/`。然后在对话中输入 `/wiki-setup`。
</details>

<details>
<summary><b>Windsurf</b></summary>

Cascade 会从 `.windsurf/rules/` 读取规则，从 `.windsurf/skills/` 读取 skill。运行
`python3 setup.py`，或者把 `.skills/*` 复制到 `.windsurf/skills/`。然后对 Cascade 说：
「set up my wiki」。
</details>

<details>
<summary><b>Codex</b></summary>

读取 `AGENTS.md` 作为项目上下文。skill 从共享的项目路径 `.agents/skills/` 发现。运行
`python3 setup.py`，或者手动把 `.skills/*` 符号链接到 `.agents/skills/`。

```bash
cd /path/to/graph-wiki && codex "set up my wiki"
```
</details>

<details>
<summary><b>Gemini CLI</b></summary>

读取 `GEMINI.md`，并从共享的项目路径 `.agents/skills/` 发现 skill。运行 `python3 setup.py`，或者
手动把 `.skills/*` 符号链接到 `.agents/skills/`。

```bash
cd /path/to/graph-wiki && gemini "set up my wiki"
```
</details>

<details>
<summary><b>Google Antigravity</b></summary>

通过 `.agent/rules/` + `.agent/workflows/` 实现 always-on。`python3 setup.py` 会铺设这两个文件，并把
skill 符号链接进项目本地的 `.agents/skills/`。
</details>

<details>
<summary><b>Kiro IDE/CLI</b></summary>

通过 `.kiro/steering/*.md` 与 `inclusion: always` 实现 always-on。`python3 setup.py` 会把 `.skills/*`
符号链接进项目本地的 `.kiro/skills/`。用 `/wiki-folder-ingest`、`/wiki-query` 等调用。
</details>

<details>
<summary><b>OpenCode / Aider / Factory Droid / Trae</b></summary>

它们都读取 repo 根目录的 `AGENTS.md`。`python3 setup.py` 会把 skill 符号链接进项目本地的
`.agents/skills/`（共享发现路径）。Trae 与 Trae CN 也使用这个项目内路径。
</details>

<details>
<summary><b>Hermes</b></summary>

先读取 `.hermes.md`，再回退到 `AGENTS.md`。项目本地的 skill 位于 `.agents/skills/`。

```bash
cd /path/to/graph-wiki && hermes "set up my wiki"
# 批量摄取 ~/.hermes 的记忆与会话：
/hermes-history-ingest
# 把某个主题上的 Hermes 知识拉进 vault：
/wiki-hermes <topic>
```

`hermes-history-ingest` 与其他批量历史 skill 一致：读取 `~/.hermes`（或 `$HERMES_HOME`），按主题合并
记忆与会话，并通过 `.manifest.json` 做增量运行。只需要回答一个问题时，使用 `/wiki-hermes <topic>`。
</details>

<details>
<summary><b>OpenClaw</b></summary>

读取 `AGENTS.md`（优先级 10）。从项目本地的 `.agents/skills/` 发现 skill。Skill 会自动注册为
slash command。

```bash
cd /path/to/graph-wiki && openclaw "set up my wiki"
# 挖掘 OpenClaw 历史：
/wiki-history-ingest openclaw
```
</details>

<details>
<summary><b>GitHub Copilot</b></summary>

**VS Code Chat：** 读取 `.github/copilot-instructions.md`。在 Copilot Chat 中说「set up my wiki」。

**CLI：** 从项目本地的 `.agents/skills/` 发现 skill。运行 `python3 setup.py`，或者手动把
`.skills/*` 符号链接到那里。
</details>

<details>
<summary><b>Pi</b></summary>

读取 `AGENTS.md`（从 cwd 向上查找）。从项目本地的 `.pi/skills/` 与 `.agents/skills/` 发现 skill。
运行 `python3 setup.py`，或者手动把 `.skills/*` 符号链接到 `.pi/skills/`。

```bash
cd /path/to/graph-wiki && pi "set up my wiki"
# 挖掘 Pi 会话历史：
/wiki-history-ingest pi
```
</details>

<details>
<summary><b>CodeAgent</b></summary>

读取 `AGENTS.md` 作为项目上下文。从 `.cac/skills/` 发现 skill。运行
`graph-wiki setup --agent codeagent`，或者手动把 `.skills/*` 符号链接到 `.cac/skills/`。
</details>
