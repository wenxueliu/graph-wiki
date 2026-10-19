[English](configuration.md) | 简体中文

# 配置

## 配置如何解析

Skill 按以下顺序解析 vault 路径：

0. **内联 vault 覆盖（`@name`）** —— 请求中任意位置的 `@<name>` token 会直接解析
   `~/.obsidian-wiki/config.<name>`，覆盖以下所有层级，**但仅对该请求生效**。
1. **从 CWD 向上查找** —— 先在当前目录找 `.env`，再逐级向上到 `$HOME`。在第一个包含
   `OBSIDIAN_VAULT_PATH` 的文件处停止。
2. **全局配置** —— `~/.obsidian-wiki/config`。
3. **提示 setup** —— 两者都不存在时，你会被告知去运行 setup。

解析之后，skill 还会读取 `$OBSIDIAN_VAULT_PATH/AGENTS.md`（如果存在）。这里是放 owner 专属约定的地方
——领域词汇、摄取偏好、写作风格、项目范围——它们会覆盖框架默认值，对所有 skill 生效。

`~/.obsidian-wiki/config` 与 `.env` 使用相同的 `KEY=value` 格式。可从 [`.env.example`](../.env.example)
开始。

## Knowledge Pack 与 vault 布局

Knowledge Pack 在 setup 时选定，其稳定绑定以 `OBSIDIAN_KNOWLEDGE_PACK` 记录在解析后的配置中。
`knowledge-packs/<name>/` 下的每个内置 pack 都包含一个语义的 `profile.json`，以及物理的
`layout.json`、`routing.json`、`routing.md`、schema、术语策略、规则与 vault 模板。

Knowledge Profile 定义目的、范围、知识类型、提取策略、证据检查、新鲜度触发条件与检索优先级。Vault
Layout 定义内容根目录、系统区、路径模板与确定性的页面路由。它们是两个不同的概念，但当前版本一对一发
行，因此一次 setup 选择就产生一份完整的领域契约。

Setup 会把 Profile、Layout 与 routing 的完整性哈希记录到
`$OBSIDIAN_VAULT_PATH/_meta/knowledge-pack.json`。该标记随 vault 一起移动，是当前生效 Knowledge Pack
的事实来源。Setup/repair 会重新加载指定的内置契约，并在任何记录的哈希过期时失败关闭；正常运行则消费
由此产生的已验证快照。已编译 context 把这份契约暴露为
`optional_metadata.active_knowledge_pack`；下游 skill 不会重新打开 Pack 文件，也不会独立重建该值。

Setup 还会把低频 context 编译到 `$OBSIDIAN_VAULT_PATH/_meta/context/wiki-context.json`，或
`OBSIDIAN_CONTEXT_SNAPSHOT` 指定的绝对路径。正常 workflow 复用该快照，而不必在每次调用时展开 owner
rules、Writing Profile、Profile、Layout、routing 与稳定元数据。有意更改上述任何输入后，请运行
setup/repair。

使用 `obsidian-wiki setup --list-knowledge-packs` 查看可用的 Knowledge Pack，并在 setup 时用
`--knowledge-pack` 选择一个。我们假定一个 vault 服务于一种知识目的，因此摄取会对照固定的 Profile 检查
来源兼容性，而不是自动侦测并切换领域。把既有 vault 换成另一个 Pack 需要内容感知的迁移；编辑 `.env`、
重命名目录或手工修改标记都不是受支持的切换机制。

内置的 Knowledge Pack 有：

- `default`：通用的 concepts、entities、skills、references 与 projects。
- `software-knowledge`：软件领域 entities，并有显式的 architecture 与 operations 类型。
- `book-knowledge`：书籍、作者、论点、文学要素与带日期的阅读笔记。它针对书籍/文本摄取优化，不提供
  软件项目路由。

不要把 Knowledge Profile 与「profile」这两个既有用法混淆：

- **Named Vault Profile**，例如 `config.work`，通过 `@work` 选择一个 vault。
- 全局 **Writing Profile**，位于 `WRITING.md`，只控制语言与风格。

二者都不会改变当前生效的 Knowledge Profile 认为什么才是持久或权威的。

## 全局 wiki 写作 profile

Setup 在每个平台上都会创建 `~/.obsidian-wiki/WRITING.md`。它从不覆盖已有的 profile。用它表达跨项目
共享的写作偏好，例如：

```markdown
## Language

用中文写作。技术标识符保持原样。

## Tone and Voice

简洁、直接、务实。

## Avoid

避免填充语、重复与无依据的论断。
```

优先级依次是：框架不变量与任务要求，其次项目 `AGENTS.md`、vault `AGENTS.md`，最后全局 `WRITING.md`。
该 profile 只影响新起草或重写的自然语言 wiki 内容。它不能改变 schema、provenance、JSON、结构化日志、
patch 或直通来源文本。缺失、空或不可读的 profile 不会阻塞操作。

确定性的 `lint`、`trust-record` 与 `trust-check` 命令使用相同的 vault 范围解析：显式路径不继承任何
无关配置，`@name` 只读取 `~/.obsidian-wiki/config.<name>`，否则在全局配置之前由最近的 CWD `.env`
优先。Schema 设置只从同一个解析后的配置读取，因此一个 vault 的 lifecycle 扩展不会泄漏到另一个 vault。

## 核心

| 变量 | 作用 | 默认值 |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | **必填。** 你的 vault 的绝对路径 | — |
| `OBSIDIAN_WIKI_REPO` | 本 repo 克隆的位置（由 setup 设置；用于查找 skill/资源） | *自动* |
| `OBSIDIAN_SOURCES_DIR` | 逗号分隔的来源目录，用于摄取文档 | *（空）* |
| `OBSIDIAN_MAX_PAGES_PER_INGEST` | 每次摄取最多创建或更新多少个页面 | `15` |
| `OBSIDIAN_LINK_FORMAT` | `wikilink` → `[[concepts/foo]]`，或 `markdown` → `` [text](path.md) ``。只影响之后的写入——既有内容绝不会被迁移 | `wikilink` |
| `LINT_SCHEDULE` | 健康检查频率：`daily` \| `weekly` \| `manual` | `weekly` |
| `WIKI_TOKEN_WARN_THRESHOLD` | `wiki-status` 使用的 token footprint 警告阈值（估算 token，按 4 字符/token 启发式）。`0` 禁用警告 | `100000` |

### 稳定的已编译 context

这些变量存在于 `.env.example`。Setup 在创建项目 `.env` 时会补齐它们；空值使用下表的默认值。它们存放
的是名称与绝对路径，而不是多行的规则或 routing 内容。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `OBSIDIAN_KNOWLEDGE_PACK` | 当前生效的原子 Profile/Layout/Routing pack | `_meta/knowledge-pack.json` 中的名称 |
| `OBSIDIAN_OWNER_RULES_PATH` | 编译进 context 的 owner rules | `<vault>/AGENTS.md` |
| `OBSIDIAN_WRITING_PROFILE_PATH` | 编译进 context 的 Writing Profile | `~/.obsidian-wiki/WRITING.md` |
| `OBSIDIAN_VAULT_METADATA_DIR` | 稳定的 vault 元数据与 Knowledge Pack 标记根目录 | `<vault>/_meta` |
| `OBSIDIAN_TAXONOMY_PATH` | 受控 taxonomy 来源 | `<metadata-dir>/taxonomy.md` |
| `OBSIDIAN_CONTEXT_SNAPSHOT` | 持久化的已编译 context JSON | `<metadata-dir>/context/wiki-context.json` |

manifest、index、hot cache、logs、ingest Job、当前 CWD 与内联覆盖仍然是动态运行时状态。它们不会仅因
稳定 context 被编译就被视为不可变。

本地 git repo 克隆可以放在 `OBSIDIAN_SOURCES_DIR` 中（公开或私有，任何托管方）。先在本地克隆，再把
路径加进去。Repo 目录会通过 `.git` 文件夹自动识别，并用 `git ls-files` 枚举，因此该 repo 自身
`.gitignore` 排除的内容——`node_modules`、构建产物、venv、密钥——会被自动跳过，而不依赖硬编码的
跳过列表。

## 历史摄取

| 变量 | 作用 | 默认值 |
|---|---|---|
| `CLAUDE_HISTORY_PATH` | Claude 数据的位置 | *从 `~/.claude` 自动发现* |
| `CODEX_HISTORY_PATH` | Codex 数据的位置 | `~/.codex` |
| `HERMES_HISTORY_PATH` | Hermes 数据的位置 | `~/.hermes` |
| `OPENCLAW_HISTORY_PATH` | OpenClaw 数据的位置 | `~/.openclaw` |
| `COPILOT_HISTORY_PATH` | Copilot CLI 数据的位置 | `~/.copilot/session-state` |
| `PI_HISTORY_PATH` | Pi 会话的位置 | `~/.pi/agent/sessions` |
| `WIKI_SKIP_PROJECTS` | 逗号分隔的子串；项目目录名匹配任意一个时，在 scan、delta 与 manifest 步骤中被跳过。例如 `archived,scratch,sandbox` | *（空）* |
| `WIKI_SESSION_BRAIN_DIR` | session-brain sidecar 的写入位置 | `~/.claude/session-brain` |

## Staged writes 与 trust

| 变量 | 作用 | 默认值 |
|---|---|---|
| `WIKI_STAGED_WRITES` | 为 `true` 时，LLM 写入的页面落入 `_staging/` 等待人工复核，而不是直接进入 live vault。用 `/wiki-stage-commit` 提升它们 | `false`——直接写入 |
| `OBSIDIAN_TRUST_STRICT` | 为 `1` 时，`obsidian-wiki lint` 把缺失 trust 字段、ledger 错误、过期复核与分数不匹配视为失败而非警告。等同于 `lint --strict-trust` | *（未设置）* |
| `OBSIDIAN_ALLOWED_LIFECYCLES` | 该解析后 vault 的逗号分隔 lifecycle 扩展 | *（仅框架默认值）* |
| `OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES` | 该解析后 vault 的逗号分隔 relationship 类型扩展 | *（仅框架默认值）* |
| `OBSIDIAN_REQUIRED_TRUST_FIELDS` | 逗号分隔的实际生效必填 trust 字段。允许值：`base_confidence`、`lifecycle`、`lifecycle_changed`、`updated`；未知值失败关闭 | lint 为 `base_confidence,lifecycle`；独立 trust 命令还包括 `updated` |
| `OBSIDIAN_SCHEMA_SOURCE` | 在机器报告中输出的 owner 权威定位符 | 存在覆盖时为 `config:<resolved-config-path>` |

Schema 解析优先级是 CLI 参数 > 解析后的环境/配置值 > 框架默认值。Lifecycle 与 relationship 类型的
扩展列表是叠加到框架默认值上；CLI 的必填字段值会替换环境的必填性。仅 CLI 的 schema 覆盖使用
`cli:<context>` 作为来源标签，而不会声称来自配置文件。如果 CLI 与解析后的配置都贡献了覆盖，报告使用
`cli+config:<resolved-config-path>`，除非 `--schema-source` 或 `OBSIDIAN_SCHEMA_SOURCE` 显式提供了
owner 权威。

这四个 schema 变量是 `OBSIDIAN_ALLOWED_LIFECYCLES`、`OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES`、
`OBSIDIAN_REQUIRED_TRUST_FIELDS` 与 `OBSIDIAN_SCHEMA_SOURCE`。其中任何一个存在时，它的值以及每个
逗号分隔项在去除首尾空白后都必须非空。空值、重复逗号与结尾逗号都会失败关闭并退出码 1；要使用框架默认
值请彻底删除该变量。可分发的 `.env.example` 为这四个变量都提供了安全的注释示例。

Staged 页面在被提升之前不会出现在 Obsidian 的图谱中。该模式开启时，`wiki-status` 会优先列出待处理的
staged writes。对于 text-ingest Job，staged unit 保持 `awaiting_review`，并且在每个必需 artifact
都被接受并 live 之前不会增加 `units_integrated`，也不会推进永久 source manifest。即使该模式关闭，
`_staging/` 目录也会在 setup 时创建。

## Vault Skill Factory

`vault-skill-factory` 把成熟的精选页面变成可移植的 Agent Skill。生成的 skill 落入一个 **复核目录**
——绝不自动安装，绝不写进 `.skills/`。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `SKILL_FACTORY_OUTPUT_DIR` | 生成 skill 的写入位置 | `<vault>/_generated-skills` |
| `SKILL_FACTORY_MATURITY` | 哪些 lifecycle 状态算作足够成熟可供采集（带 `tier: core` 的页面也算） | `reviewed,verified` |

## Text ingest 提取与分块

Text ingest V1 使用无依赖的 UTF-8 字节预算，而不是特定模型的 tokenizer。`wiki-folder-ingest` 从目标
vault 的配置解析这些值，并把实际生效的值记录进每个持久化 Job。预算变化会创建新计划，而不是续跑一个
不兼容的未完成 Job。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS` | 每个 Job 最大并发的隔离 unit-to-Packet 提取 worker 数；宿主可能施加更低的上限 | `4` |
| `WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES` | 小于等于该大小的完整来源使用串行 inline 提取/归并，不写 Packet 文件；`0` 禁用 | `16000` 与硬上限中的较小者 |
| `WIKI_TEXT_CHUNK_TARGET_BYTES` | 每个已规划文本单元偏好的 UTF-8 字节大小 | `48000` |
| `WIKI_TEXT_CHUNK_MIN_BYTES` | 一个标题成为偏好切分点之前的最小累计大小 | 目标值的一半（默认 `24000`） |
| `WIKI_TEXT_CHUNK_HARD_MAX_BYTES` | 每个已规划文本单元的绝对 UTF-8 字节上限 | `64000` |
| `WIKI_TEXT_CHUNK_STRATEGY` | `adaptive_sections`、`strict_sections`，或已安装的自定义策略名 | `adaptive_sections` |
| `WIKI_TEXT_CHUNK_OPTIONS` | 传给所选策略的 JSON 对象 | `{}` |

这三个预算必须是正整数，且 最小值 ≤ 目标值 ≤ 硬上限，workflow 硬上限不得超过 64,000 字节。
Direct-extraction 阈值必须是非负整数且不大于硬上限。Inline 来源为一个逻辑单元保留 provenance、
staged review、可续跑与收尾能力，但不创建 Packet 文件。`adaptive_sections` 会合并相邻的短段落直到
达到最小值，并可能把略高于目标值的小尾巴合并进来，只要仍在硬上限内。`strict_sections` 保留旧行为：
每次 heading-path 变化都结束一个单元。直接使用 CLI 时，对应参数会按每次调用覆盖命令默认值。

自定义策略名来自受信任的已安装 Python 包，通过 `obsidian_wiki.text_chunk_strategies` entry-point 组
注册。选择一个策略会执行该包的代码；不要配置不受信任的扩展。

提取并发作用于整个 Job 中的所有 packet unit，包括来自同一来源文档的多个 unit。Worker 写入各自不同的
Packet 文件，绝不改动共享 wiki 状态。已完成的 Packet 会被缓冲，并按稳定的 source/unit 顺序串行归并，
因此提高该值能加速提取，而不会让页面写入变成并发。

PageIndex 不是 V1 的依赖。未来的 PDF 流水线可能只把它当作本地硬预算切分器背后的 structure provider；
在那条流水线存在之前，PDF 仍然是显式不支持的。

## QMD 语义搜索（可选）

默认情况下，`wiki-folder-ingest` 与 `wiki-query` 使用 Grep/Glob——功能完整，无需额外设置。如果你的
vault 变得很大，或你想在来源之间做概念级匹配，可以接入 [QMD](https://github.com/tobi/qmd)，通过 MCP
或让 agent 调用本地 `qmd` CLI。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `QMD_WIKI_COLLECTION` | 索引你已编译 wiki 页面的集合——由 `wiki-query` 使用 | *（空——禁用）* |
| `QMD_PAPERS_COLLECTION` | 索引你原始来源文档的集合——由 text-ingest 流水线使用 | *（空——禁用）* |
| `QMD_TRANSPORT` | `mcp`（agent 配置的 MCP server）或 `cli`（本地 `qmd` 二进制） | `mcp` |
| `QMD_CLI_SEARCH_MODE` | `quality`（重排，最佳相关性）、`balanced`（`--no-rerank`）或 `fast`（仅语义） | `quality` |
| `QMD_CLI` | 当 `qmd` 不在 `PATH` 上时覆盖其二进制路径 | `qmd` |

**设置：**

```bash
qmd collection add /path/to/vault --name my-wiki
qmd collection add /path/to/sources --name papers
```

```env
QMD_WIKI_COLLECTION=my-wiki
QMD_PAPERS_COLLECTION=papers
QMD_TRANSPORT=mcp
QMD_CLI_SEARCH_MODE=quality
```

> **两个集合必须保持不相交。** `wiki-query` 把它们当作两个独立层——已编译知识 vs. 原始暂存——并分别
> 引用。由于 `OBSIDIAN_VAULT_PATH` 包含 `_raw/`，直接 `qmd collection add <vault>` 会把两层合并，
> 让被取代的草稿变得可检索，并像已编译页面一样被引用。
>
> QMD 没有 `--ignore` 参数，因此请通过编辑 `~/.config/qmd/index.yml` 来限定集合范围：
>
> ```yaml
> collections:
>   my-wiki:
>     path: /path/to/vault
>     pattern: "**/*.md"
>     ignore:
>       - "_raw/**"
>       - "log.md"
> ```
>
> 然后运行 `qmd update`。

**开启后有什么变化：**

- `wiki-query` 在回退到 Grep 之前，会对你的 wiki 集合跑一次语义检索（lex+vec）——即使精确用词不匹配，
  也能找到概念相关的页面。
- `wiki-folder-ingest` 在写入新页面之前，会针对你的 papers 集合协调 Packet 或 inline 传输归并——
  浮现相关来源、发现矛盾，并决定是新建页面还是并入既有页面。

两者都能优雅降级：集合名未设置时，它们会静静跳过 QMD 步骤并使用 Grep。

## `_raw/` 暂存目录

`_raw/` 是你 vault 内部用于未处理 UTF-8 文本采集的暂存区。把受支持的文本文件丢进去，下一次
`wiki-folder-ingest` 运行就会处理它们；完成归并后，原始文件会移到 `_raw/_archived/`，从而既被保留
又不会被重复处理。

在实时代码会话中最快的喂养方式：

```text
/wiki-capture --quick
```

它会扫描当前对话，提取 bug 与坑点，并在 60 秒内写出结构化草稿文件——不派发 subagent，也不写 manifest。

要把所有等待中的内容提升：

```text
/wiki-folder-ingest promote my raw pages
```

该目录由所选 workflow 布局在 `wiki-setup` 期间自动创建。

### 浏览器采集扩展

本 repo 在 [`extensions/brain-capture/`](../extensions/brain-capture/) 中包含一个零构建的 Chrome
扩展，用于把网页与选中的文本直接保存进 `_raw/`。

1. 打开 `chrome://extensions`
2. 启用 **Developer mode**
3. 点击 **Load unpacked**
4. 选择 `extensions/brain-capture`

要从本 repo 的克隆中找出已配置的 `_raw` 文件夹：

```bash
awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 "/_raw"; exit}' "$(git rev-parse --show-toplevel)/.env"
```

## 把 vault 同步到 GitHub

你的 vault 是一个纯 markdown 文件目录——把它推送到一个私有 GitHub repo，你就免费获得版本历史、备份与
跨设备同步。`obsidian-wiki setup` 与 `python3 setup.py` 都会在安装时提供配置它的选项；它们共用同一套
实现（`obsidian_wiki/sync.py`），因此 pip 安装与源码安装得到完全一致的过程。

**Setup 会做什么：**

1. 如果 vault 还不是 repo，就 `git init`
2. 创建一个 `.gitignore`，排除 Obsidian 的 workspace/cache 文件
3. 设置你提供的 remote——vault 自己的 `git remote`（而不是某个配置文件）才是「同步是否已配置」的事实
   来源，因此它不会漂移
4. 可选地添加一个 `wiki-sync` shell 别名
5. 可选地安装一个每小时运行的 cron 任务

**随时运行同步：**

```bash
wiki-sync            # 由 setup 添加的别名
obsidian-wiki sync   # 或者直接调用
```

每次运行都会暂存所有变更，以 `sync 2026-07-30 14:00` 提交并推送。

**之后配置，或手工配置：**

```bash
obsidian-wiki sync-setup https://github.com/you/my-wiki.git
# 或者：
cd /path/to/your/vault
git init
git remote add origin https://github.com/you/my-wiki.git
```

**通过 cron 每小时自动同步：**

```
0 * * * * obsidian-wiki sync --vault /path/to/your/vault >> ~/.obsidian-wiki/sync.log 2>&1
```

> 如果你的 vault 包含个人笔记，请把 repo 保持为 **私有**。不会向任何第三方服务发送任何东西——你的
> vault 只存在于你自己的机器与你的 GitHub 账号中。

## Visibility 标签（可选）

页面可以带一个 `visibility/` 标签，标记它预期的可见范围。这 **完全是可选的** ——未打标签的页面行为
与以往完全相同。系统保持单 vault、单一事实来源。

| 标签 | 含义 |
|---|---|
| *（无）* | 等同于 `visibility/public`——在所有模式下可见 |
| `visibility/public` | 显式公开 |
| `visibility/internal` | 仅团队——在过滤模式下被排除 |
| `visibility/pii` | 敏感——在过滤模式下被排除 |

**过滤模式** 是 opt-in 的，当查询中出现「public only」「user-facing answer」「no internal content」
或「as a user would see it」等说法时触发。默认模式显示全部内容。

`visibility/` 标签是 **系统标签** ——它们不计入 5 个标签的上限，并在 taxonomy 中与领域/类型标签分列。
