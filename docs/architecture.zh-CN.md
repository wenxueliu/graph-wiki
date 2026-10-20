[English](architecture.md) | 简体中文

# 架构

wiki 是产物，agent 是维护者，Obsidian 是查看器。

临时 workflow 产物既不属于 wiki，也不属于已安装的 skill。每一次顶层 skill 调用都会创建一个唯一的
`run_id` 与一个绝对路径的临时 `artifacts_dir`；它的各个步骤、重试与子 workflow 共用这一绑定。之后的
调用会创建另一个目录，从而避免上下文、计划与报告在不同运行之间混在一起。

低频的 Wiki context 在 setup 时单独编译到 vault 元数据区下的持久快照中。运行时的 artifacts 目录以
链接方式引用这个只读快照；它们不会反复内嵌 Profile、Layout、routing、owner rules 或 Writing Profile。
动态的 Job、manifest、index、hot-cache 与调用状态则不属于已编译快照的生命周期。

Skill 告诉 AI agent 如何操作 vault。少量无依赖的 Python 辅助工具负责那些必须确定性的部分，包括
hashing、text range planning 与精确区间物化；提取与知识归并仍然是 agent 的工作。

## Knowledge Pack：Profile 与 Layout

每个 vault 在 setup 时选择一个 **Knowledge Pack**。一个 pack 有意绑定两份契约：

- **Knowledge Profile**（`profile.json`）是语义层面的。它定义 vault 的目的与范围、持久化知识类型、
  提取保留或省略什么、什么证据具有权威性、哪些检查确立信任、什么会让知识过期，以及检索应该如何排序
  证据。
- **Vault Layout**（`layout.json`、`routing.json` 与 `routing.md`）是物理层面的。它定义 live 内容根
  目录、系统区与跳过区、路径模板、命名占位符，以及确定性的 page-type-to-path 路由。

尽管当前发行版把二者打包成一比一，这个区分仍然重要。一条软件 Decision 无论存放在扁平的
`decisions/` 下，还是嵌套在某个项目下，其含义与证据要求都不变；反过来，一个通用的 `concepts/`
目录并不能告诉 agent 它正在编译的是科学证据、历史解读，还是软件设计。

我们假定一个 vault 服务于一种知识目的。因此 setup 只选择一次 pack，并把 Profile、Layout 与 routing
的哈希绑定进 `_meta/knowledge-pack.json`。摄取 **不会** 为每个来源去猜一个新领域。它会对照当前生效的
Profile 检查来源，并遵循 Profile 的 `ask`、`stage` 或 `reject` 失配动作。Source adapter 只回答如何读
取一种格式，它不决定 vault 应该记住什么。

内置的 pack 有 `default`、`software-knowledge` 与 `book-knowledge`。它们位于顶层
`knowledge-packs/` 产品目录中，并作为 `obsidian_wiki/_data/knowledge-packs/` 安装进 Python 包。
Workflow 通过共享的 Pack loader 消费它们；它们不拥有也不内嵌 Pack 定义。

## 四个阶段

每次你喂养这个大脑，都会经过以下几个阶段：

### 1. Ingest（摄取）

Text ingest 会发现自己本地 UTF-8 的 Markdown、纯文本与 reStructuredText 文件，并提供两个入口。
`wiki-folder-ingest` 是可恢复的 Job/Packet 流水线。`wiki-ingest` 是只依赖 skill 的轻量路径：一个确定性
的流式分块器把每个 Source File 规范化为 ingest document，因此小文件产生一个 document，大文件产生多个。
不支持的格式会一直可见，绝不会被默默当作文本解码。

### 2. Pull information（提取信息）

每个待处理的 ingest document 都由父 Agent 派发给一个全新的 `general-purpose` subagent，只带上它的
plan 绑定与冻结的 wiki context。Worker 只物化一个经过哈希校验的区间，并把该区间视为一份完整输入文档。
Subagent 之间不共享来源正文与模型上下文，因此原始文件大小永远不会撑爆单个会话。写入保持串行，以免两个
subagent 覆盖同一个规范页面。

在可恢复的 `wiki-folder-ingest` 路径中，小来源使用 inline 归并，而较大的区间通过有界隔离 worker 提取
为已验证的 Packet。持久化 Job 负责续跑、排序、staged review 与来源级完成。

每个页面在写入时，frontmatter 中还会得到 1–2 句 `summary:`——之后的查询用它在不打开页面的情况下预览。

### 3. Merge（归并）

轻量 worker 直接把新知识归并到既有的规范页面；矛盾之处与精确的 source/document 定位符都会被保留。
它在路由之前应用当前生效的 Knowledge Profile。Ingest document 的边界永远不会变成 Wiki 页面边界。
页面与 special file 校验通过后，一条原子 manifest 记录标记该 document 完成；失败不会留下记录，并且会
自然重试。可恢复路径通过 `wiki-packet-integrate` 执行等价的归并，并通过 `wiki-finalize-sources`
完成整个来源的收尾。

### 4. Schema

框架级的 provenance 与 tracking 信封是共享的，而领域特定的知识类型与必填字段来自当前生效的
Knowledge Pack。Agent 负责维持一致性：category 保持一致，wikilink 指向真实页面，index 反映实际存在
的内容。把 vault 换成另一个 Pack 是一次内容感知的迁移，而不是摄取过程中的自动 schema 扩展。

`wiki-ingest` 不创建 Job、unit 状态机、Packet、提取转储或持久化 worker 目录；`.manifest.json` 本身
就是它的完成台账。`wiki-folder-ingest` 则有意保留持久化 Job 与 Packet，以获得可抗中断的续跑与 staged
review。

## 循环

1. Agent 解析 vault 路径（`@name` → `.env` → 配置目录中的 `config`，默认 `~/.obsidian-wiki`）
2. Agent 读取 `.manifest.json`，知道哪些已经做过
3. Agent 从绑定的 Knowledge Pack 加载当前生效的 Knowledge Profile 与 Vault Layout
4. Agent 读取相关 skill 获取指令
5. Agent 使用它的内置工具完成工作
6. 所选 skill 要么运行由父 Agent 派发的 ingest document subagent，要么运行绑定 Job 的 range worker
7. 所选完成边界要么提交一个已验证 document，要么提交一个完整来源
8. 输出是标准的、Obsidian 兼容的 markdown，带 frontmatter 与 `[[wikilinks]]`

## Vault 结构

以下是 `default` Knowledge Pack 的布局。其他 Pack 提供不同的内容根目录；运行时 workflow 会枚举当前
生效的 Layout，而不是假定这些目录名。

```
$OBSIDIAN_VAULT_PATH/
├── index.md                # 主索引——每个页面，始终保持最新
├── log.md                  # 按时间排列的活动日志
├── hot.md                  # 近期活动的约 500 词语义快照
├── .manifest.json          # 摄取台账：路径、时间戳、产出的页面
├── _meta/
│   ├── knowledge-pack.json # 当前 Pack 的身份与契约哈希
│   ├── taxonomy.md         # 受控标签词表
│   ├── ingest-jobs/        # 持久化的 wiki-folder-ingest Job 与有界 Packet
│   └── *.base              # Obsidian Bases 仪表盘定义
├── _insights.md            # 图谱分析：枢纽、桥梁、死胡同
├── _raw/                   # 暂存——丢入粗略笔记，下次摄取会将其提升
├── _staging/               # WIKI_STAGED_WRITES=true 时的复核队列
├── _archives/              # 用于 rebuild/restore 的带时间戳快照
├── _readouts/              # wiki-narrate 产生的叙述性 readout
├── concepts/               # 抽象想法、模式、心智模型
├── entities/               # 具体事物——人物、工具、库、公司
├── skills/                 # 操作方法类知识、技巧、流程
├── references/             # 事实查询——规格、API、配置
├── synthesis/              # 连接多个概念的跨领域分析
├── journal/                # 与时间相关的条目——每日日志、会话笔记
└── projects/
    └── <project-name>.md   # 每个项目一个页面，由 wiki-update 同步
```

项目特定的知识放在 `projects/` 下。通用的知识放在全局类别目录中。二者都通过 `[[wikilinks]]` 交叉引用。

每个页面都带有必填 frontmatter：`title`、`category`、`tags`、`sources`、`created`、`updated`。

Typed relationships 使用 24 个 Penfield 标准类型（`part_of`、`causes`、`implements`、`contradicts`、
`supersedes` 等）。另有五个 legacy 别名——`uses`、`related_to`、`derived_from`、`extends`、
`replaces`——为既有 vault 保留，因此实际允许集是 29 种；owner 还可以从解析后的 vault 配置继续扩展。
一条有向边由 `(source, target, type)` 规范化，可以从框架的嵌套 `relationships:` 块读取，也可以从
`supports:` 这样的 Wikilink Types 顶层键，或 `[[Target|Target @supports]]` 这样的内联别名读取。新
的摄取/更新写入会保持三种投影同步；query 与 graph 消费方会把它们去重为一条边，而 lint 会报告不一致。

`hot.md` 值得特别提一句——它是一份持续更新的语义快照，每个写入 skill 都会更新它，因此下一个会话无需
爬遍整个 vault 就能接着上一次继续。

## 核心原则

- **编译，而不是检索。** wiki 是预先编译好的知识。更新既有页面——不要追加或重复。
- **追踪一切。** 摄取后写 `.manifest.json`；任何写入后更新 `index.md`、`log.md` 与 `hot.md`。
- **用 `[[wikilinks]]` 连接。** 正是这一点让它成为知识图谱，而不是一个文件目录。
- **frontmatter 是必填的。** 每个页面，每次都要。
- **单一事实来源。** visibility 标签决定内容如何显现——它们绝不复制或分离内容。

## 我们在 Karpathy 模式之上加了什么

[原始 gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 是种子：把知识一次性
编译成互相连接的 markdown 并保持更新，而不是反复向 LLM 问同样的问题、或每次都跑 RAG。以下是在它之上
构建出来的东西。

- **Delta 追踪。** 一个 manifest 追踪每个已摄取的来源文件。之后回来时，它会计算 delta，只处理新增或
  变更的内容。你不必每次都重新摄取你的整个文档库。

- **基于项目的组织。** 项目特定的知识归入项目下，通用知识归入全局。二者交叉引用。十个代码库，vault 里
  就是十个空间。

- **归档与重建。** 当 wiki 偏离来源太远时，把整个 vault 归档（带时间戳的快照，什么都不会丢）并重建。
  也可以恢复任意一个先前的归档。

- **上下文有界的 text ingest。** Markdown、text 与 reStructuredText 来源会被确定性地切分为精确的字节
  区间。Agent 历史保留各自的专用摄取 skill；其他格式则等待显式的 structure provider，而不是使用不安全
  的通用兜底。

- **跨 agent 的定向搜索。** 在 Claude Code 里执行 `/wiki-codex "rust ownership"`，就能找到你在该主题
  上的 Codex 会话，提取相关片段，蒸馏成页面，并返回一个综合答案。它主题优先，而不是会话优先。每个
  agent 有自己的提取策略。配合 `/memory-bridge diff` 就能看到每个工具独有的贡献。

- **审计与 lint。** 孤立页面、失效 wikilink、过期内容、矛盾、缺失 frontmatter——外加一个「已摄取 vs.
  待处理」的仪表盘。

- **身份消解。** `wiki-dedup` 找出同一概念的不同命名页面（「RSC」vs.「React Server Components」）并
  合并它们。

- **可选交叉链接。** 摄取完成后，单独运行 cross-linker 扫描未被链接的提及并把它们织入图谱；它不属于
  摄取 Job 的完成边界。

- **标签词表。** `_meta/taxonomy.md` 中的受控词表，配有一个可在全 vault 范围审计并规范化标签的 skill。

- **Provenance 追踪。** 每条论断都被打上标记：extracted（默认）、`^[inferred]`（LLM 综合）或
  `^[ambiguous]`（来源互相矛盾）。frontmatter 中的 `provenance:` 块按页面汇总其构成，`wiki-lint` 会
  标出正在滑向纯推测的页面。你始终能分辨你的 wiki 知道什么、又猜了什么。

- **Trust ledger。** `obsidian-wiki trust-record` / `trust-check` 会对照材料指纹记录并校验经人工批准的
  置信度复核，因此 CI 可以以「确实有人检查过」作为门禁。

- **显式扩展点。** PDF structure provider 与多模态/结构化数据流水线被推迟；不支持的输入会被报告其检出
  类型与原因。

- **Wiki 洞察。** `wiki-status` 可以分析 vault 自身的形态：主要枢纽、桥梁页面（移除后会把图切分的
  节点）、标签簇内聚度、打分的意外连接、自上次运行以来的图谱 delta，以及这一结构最适合回答的问题。
  输出写入 `_insights.md`。

- **图谱导出与导入。** `wiki-export` 把 wikilink 图谱转换成 `graph.json`、`graph.graphml`
  （Gephi/yEd）、`cypher.txt`（Neo4j）、自包含的交互式 `graph.html`，或一个 OKF bundle。
  `wiki-import` 能把它们读回来。

- **分层检索。** `wiki-query` 先读标题、标签与摘要，只有当这个低成本过程无法回答时才打开页面正文。
  说「quick answer」可以强制只走索引。查询成本从 20 个页面到 2000 个页面基本持平。

- **Session brain。** 在你原始 agent 会话历史之上构建的主题图谱，让你能找回某事发生在哪个会话。见
  [Session Brain](session-brain.zh-CN.md)。

- **Staged writes。** 设置 `WIKI_STAGED_WRITES=true`，LLM 写入的页面会先在 `_staging/` 排队等待复核，
  之后再落入 live vault。

## Open Knowledge Format

vault 格式在结构上符合 [OKF v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
——带 YAML frontmatter 的 markdown、category 子目录、保留的 `index.md`/`log.md`。

`wiki-export`（OKF 模式）与 `wiki-import` 是桥梁：它们在原生 frontmatter
（`title`/`category`/`tags`/`sources`/`created`/`updated` + `summary`）与 OKF
（`type`/`title`/`description`/`resource`/`tags`/`timestamp`）之间转换，让 vault 可以与任何 OKF 工具
交换。

OKF 往返是无损的。`graph.json` 往返则不是——它携带结构，而不是页面正文。

## 仓库布局

```
obsidian-wiki/
├── .skills/                             # ← 规范 skill 定义（事实来源）
│   └── <skill-name>/SKILL.md            #   49 个 skill——见 docs/skills.md
│
├── knowledge-packs/                     # 内置 Profile + Layout pack（default、book-knowledge、software-knowledge）
├── workflows/                           # workflow-backed skill 的行为事实来源
│   ├── <name>.yaml                      #   22 个 workflow
│   ├── scripts/                         # workflow 调用的确定性辅助脚本
│   └── templates/wiki-setup/            # vault 脚手架模板（index、log、hot、manifest、WRITING）
├── obsidian_wiki/                       # Python 包——CLI、setup、sync、session brain
├── scripts/                             # 独立辅助脚本（daily-update、manifest、wiki-notify）
├── tools/                               # sync_workflow_skills.py、check_readme_sync.py
├── tests/                               # pytest 测试集
├── example/                             # 消费 Knowledge Pack 的示例项目（design、book）
├── extensions/brain-capture/            # 零构建的 Chrome 采集扩展
│
├── CLAUDE.md                            # Bootstrap → Claude Code / Kilocode（→ AGENTS.md）
├── GEMINI.md                            # Bootstrap → Gemini CLI（→ AGENTS.md）
├── AGENTS.md                            # Bootstrap → Codex、OpenCode、Aider、Droid、Trae、Hermes、OpenClaw
├── .hermes.md                           # Bootstrap → Hermes（符号链接 → AGENTS.md）
├── .cursor/rules/obsidian-wiki.mdc      # Always-on → Cursor（alwaysApply: true）
├── .windsurf/rules/obsidian-wiki.md     # Always-on → Windsurf
├── .kiro/steering/obsidian-wiki.md      # Always-on → Kiro（inclusion: always）
├── .agent/rules/obsidian-wiki.md        # Always-on → Google Antigravity
├── .agent/workflows/obsidian-wiki.md    # Slash-command registry → Antigravity
├── .github/copilot-instructions.md      # Always-on → GitHub Copilot（VS Code Chat）
│
├── .claude/skills/   → .skills/* 的符号链接   （由 setup 创建）
├── .cursor/skills/   → .skills/* 的符号链接
├── .windsurf/skills/ → .skills/* 的符号链接
├── .agents/skills/   → .skills/* 的符号链接
├── .pi/skills/       → .skills/* 的符号链接
├── .cac/skills/      → .skills/* 的符号链接   （CodeAgent）
├── .kiro/skills/     → .skills/* 的符号链接
│
├── setup.py                             # 一条命令完成 agent 设置（跨平台）
├── .env.example                         # 配置模板
└── docs/                                # 你在这里
```

Setup 创建的全局符号链接目标列在 [Installation → What `python3 setup.py` wires up](installation.zh-CN.md#what-python3-setuppy-wires-up)。

完整模式——三层架构、页面模板、项目组织——请读
[`.skills/llm-wiki/SKILL.md`](../.skills/llm-wiki/SKILL.md)。
