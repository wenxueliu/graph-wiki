[English](skills.md) | 简体中文

# Skills 参考

全部内容都在 [`.skills/`](../.skills/) 下，共 **49 个 skill**。每个 skill 是一个包含 `SKILL.md`
的目录，当你的请求匹配其 description 时，agent 就会读取它。没有 runtime，没有插件系统，也不需要
注册步骤。

Slash command（`/skill-name`）在 Claude Code、Cursor、Windsurf 以及多数 CLI agent 中可用。在其他
agent 中，直接描述你的需求即可。

标注为 **internal** 的 skill 只能由持有其输入契约的父 skill 调用，请不要直接使用。

## 设置与 vault

| Skill | 作用 | Slash command |
|---|---|---|
| `wiki-setup` | 初始化或安全修复 vault 的配置、Knowledge Pack、核心文件与可选集成 | `/wiki-setup` |
| `wiki-switch` | 管理多个命名 vault profile，并切换当前生效的一个 | `/wiki-switch <name>` |
| `daily-update` | vault 范围内的每日维护：来源新鲜度、index、hot cache、状态文件、独立验证与日志 | `/daily-update` |
| `daily-update-setup` | 经人工批准后安装或验证每日 09:00 调度、vault 范围状态与可选终端提醒 | `/daily-update-setup` |
| `wiki-context` | internal — 按配置解析 vault，并构建其他所有 skill 共用的运行时上下文 | — |
| `wiki-setup-contract` | internal — 由 workflow 本地模板渲染带 hash 的核心 setup 契约，再合并可选集成与验收契约 | — |
| `wiki-page-contract` | internal — 将共享 wiki context 与事务范围编译为不可变的 effective page write contract | — |
| `wiki-finalize-sources` | internal — 在 exact-hash source 完成门成立时统一更新 special files，并以 manifest-last 提交一个或多个来源 | — |

## 喂养它

| Skill | 作用 | Slash command |
|---|---|---|
| `wiki-folder-ingest` | 可恢复的文本摄取：发现并规划本地来源，小文档 inline 提取，大文档隔离生成 Packet，再按 source/unit 顺序串行归并 | `/wiki-folder-ingest` |
| `wiki-ingest` | 轻量文本摄取：将每个文件统一规划为独立 ingest document，并在 fresh session 中直接归并——不创建 Job、Packet，也不调用 `claude -p` | `/wiki-ingest` |
| `wiki-ingest-document` | internal — 归并一个已规划的 ingest document，并把完成状态写入 `.manifest.json` | — |
| `wiki-source-text` | internal — 由 coordinator 指定的一个 UTF-8 区段提取为已验证的 Packet | — |
| `wiki-packet-integrate` | internal — 使用冻结的 Job context 与 page contract 验证并串行归并一个 Packet | — |
| `wiki-capture` | 把当前对话保存为结构化的 wiki 笔记；`--quick` 会在 60 秒内把发现落到 `_raw/` | `/wiki-capture` |
| `wiki-update` | 从你当前所在的项目增量蒸馏架构决策与可复用知识 | `/wiki-update` |
| `wiki-research` | 自主多轮网络研究，综合后直接归档进 vault | `/wiki-research [topic]` |
| `wiki-history-ingest` | 批量 agent 历史摄取的路由器 | `/wiki-history-ingest <agent>` |
| `claude-history-ingest` | 挖掘 Claude CLI 与 Desktop 会话，蒸馏为可追溯的 wiki 知识 | `/claude-history-ingest` |
| `codex-history-ingest` | 挖掘 `~/.codex` 会话与 rollout 日志 | `/codex-history-ingest` |
| `copilot-history-ingest` | 挖掘 GitHub Copilot CLI 会话（`~/.copilot/session-state`） | `/copilot-history-ingest` |
| `openclaw-history-ingest` | 挖掘 `~/.openclaw` 的 `MEMORY.md` 与会话 | `/openclaw-history-ingest` |
| `pi-history-ingest` | 挖掘 `~/.pi/agent/sessions` 的 JSONL 历史 | `/pi-history-ingest` |
| `wiki-agent` | 针对某个 agent 原始历史的主题优先摄取，并返回可直接用于当前会话的综合答案 | `/wiki-claude`、`/wiki-codex`、`/wiki-hermes`、`/wiki-openclaw`、`/wiki-copilot`、`/wiki-pi` |

`wiki-history-ingest` 可路由 `claude`、`copilot`、`codex`、`openclaw` 与 `pi`。目前 `.skills/` 中
没有专用的 Hermes 历史 skill；请使用 `/wiki-hermes <topic>`，它通过 `wiki-agent` 执行定向的 Hermes
摄取。

Text ingest V1 只接受 UTF-8 的 `.md`、`.markdown`、`.mdx`、`.txt` 与 `.rst`。PDF、Office 文档、
结构化数据、日志/对话记录、HTML/URL、媒体、压缩包与源代码都会被显式报告，而不会被当作通用文本处理。
Agent 历史与网络研究仍使用上表中各自的专用 skill。

## 向它提问

| Skill | 作用 | Slash command |
|---|---|---|
| `wiki-query` | 只读地从已编译 wiki 给出带引用的回答——依次走 GraphRAG、索引、QMD、局部正文与多跳 typed graph | `/wiki-query` |
| `wiki-narrate` | 针对某个主题生成带引用的简报、通俗解释或渐进式讲解 | `/wiki-narrate <topic>` |
| `wiki-digest` | 以简报形式总结你在一天、一周或一个月里学到了什么 | `/wiki-digest [period]` |
| `wiki-context-pack` | 为下游 agent 或任务生成受 token 限制、可直接引用的上下文切片 | `/wiki-context-pack` |
| `memory-bridge` | 按产出工具浏览并对比已编译的知识 | `/memory-bridge` |

## 找回过去的会话

这两个 skill 会在你的原始 agent 会话之上构建检索索引。它们把 sidecar 写在 `~/.claude/session-brain/`
（可用 `WIKI_SESSION_BRAIN_DIR` 覆盖），并且 **绝不写入 vault**。见 [Session Brain](session-brain.zh-CN.md)。

| Skill | 作用 | Slash command |
|---|---|---|
| `session-brain` | 在 agent 会话历史之上构建并维护主题图谱 | `/session-brain` |
| `session-search` | 按主题找到过去的会话，并把它的上下文载入当前对话 | `/wiki-sessions <topic>` |

> **摄取 vs. 检索。** 如果你要的是把知识永久保存为 vault 页面，用 `wiki-history-ingest`；如果你想
> 找到某件事发生在哪个会话，用这两个。

## 维护它

| Skill | 作用 | Slash command |
|---|---|---|
| `wiki-status` | 只读地报告来源增量、健康优先级与 token footprint，并可生成 vault 形态洞察 | `/wiki-status` |
| `wiki-lint` | 只读审计结构、schema、链接、来源与知识图谱健康度，并生成可复核报告 | `/wiki-lint` |
| `wiki-lint-consolidate` | 先做完整 lint dry-run，再在人工批准后应用可自动化的结构维护 | `/wiki-lint-consolidate` |
| `wiki-dedup` | 身份消解——把同一概念的不同命名页面合并 | `/wiki-dedup` |
| `cross-linker` | 发现并写入高置信页面链接、typed relationships 与 misc affinity | `/cross-linker` |
| `obsidian-vault-linker` | 仅用纯 Markdown 与 YAML 发现并写入笔记之间的 typed relationships，无需插件 | `/obsidian-vault-linker` |
| `tag-taxonomy` | 审计、规范化或扩展受控标签词表，并维护 tracking 与可选 QMD 索引 | `/tag-taxonomy` |
| `wiki-synthesize` | 发现频繁共现却没有 synthesis 页面连接的概念簇，并补齐 | `/wiki-synthesize` |
| `wiki-stage-commit` | 经逐项人工批准，把 staged 页面或 patch 提升为 live 内容 | `/wiki-stage-commit` |
| `wiki-rebuild` | 先归档，再执行 snapshot、清空重建准备或恢复旧归档 | `/wiki-rebuild` |

## 查看与搬运

| Skill | 作用 | Slash command |
|---|---|---|
| `graph-colorize` | 按 tag、category 或 visibility 为 Obsidian graph view 上色 | `/graph-colorize` |
| `wiki-dashboard` | 用 Obsidian Bases 或 Dataview 创建动态仪表盘 | `/wiki-dashboard` |
| `wiki-export` | 把图谱导出为 JSON、GraphML、Neo4j Cypher、交互式 HTML 或 OKF bundle | `/wiki-export` |
| `wiki-import` | 把 `graph.json` 导出（占位页）或 OKF markdown bundle（完整正文）导入当前 vault | `/wiki-import` |
| `obsidian-layout-adjustment` | 用 CSS snippet 调整 Obsidian 外观——标签页、侧边栏、graph 面板、笔记界面 | `/obsidian-layout-adjustment` |

## 扩展框架

| Skill | 作用 | Slash command |
|---|---|---|
| `llm-wiki` | 核心模式与架构参考，其他所有 skill 都以它为准 | `/llm-wiki` |
| `skill-creator` | 创建、修改并评估新 skill | `/skill-creator` |
| `vault-skill-factory` | 把一组成熟 vault 页面变成一个可移植的「数字专家」skill | `/vault-skill-factory` |
| `impl-validator` | 对照既定目标逐项验证实现，给出可复核的 PASS/WARN/FAIL 结论 | `/impl-validator` |

## 示例 skill 集合

[`example/design/`](../example/design/) 包含一个自包含的单产品设计示例，带项目级 `AGENTS.md`
以及五个示例 Agent Skill，分别覆盖需求、设计、实现计划、测试设计与问题诊断。这些示例消费
`software-knowledge` Pack，但不会作为框架 skill 安装。

## 推荐搭配：Kepano 的 Obsidian Skills

本框架负责知识管理流程——摄取、查询、lint、重建。若要精通 Obsidian 格式，可以一并安装
[**kepano/obsidian-skills**](https://github.com/kepano/obsidian-skills)。这是可选项，但能提升产出
质量：

| Skill | 它带来的能力 |
|---|---|
| `obsidian-markdown` | 正确的 Obsidian 语法——wikilink、callout、embed、properties |
| `obsidian-bases` | 创建与编辑 `.base` 文件（类数据库的笔记视图） |
| `json-canvas` | 创建与编辑 `.canvas` 文件（可视化思维导图、流程图） |
| `obsidian-cli` | 通过 CLI 与运行中的 Obsidian 交互 |
| `defuddle` | 从网页提取干净 markdown——减少噪音与摄取时的 token |

```bash
npx skills add kepano/obsidian-skills
```

两个项目都遵循同一套 [Agent Skills 规范](https://agentskills.io/specification)，因此可以共存于同一个
`.skills/` 目录而互不冲突。

## 编写你自己的 skill

见 [Contributing → 新增一个 skill](contributing.zh-CN.md#新增一个-skill)，或者直接问：

> 「创建一个 skill，从我的日记条目生成每周总结」

`skill-creator` 会引导你在 `.skills/` 中起草、测试并打磨它。
