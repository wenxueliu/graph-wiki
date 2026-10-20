[English](cli.md) | 简体中文

# CLI 参考

`obsidian-wiki` Python 包提供了一个 CLI，覆盖安装、检查，以及工作流中确定性的部分——也就是不需要
LLM 的那些事。其余部分都是 agent 执行的 [skill](skills.zh-CN.md)。

```bash
pip install obsidian-wiki
obsidian-wiki --help
obsidian-wiki --version
```

不带子命令运行 `obsidian-wiki` 时，默认执行 `setup`。

## 安装与检查

| 命令 | 作用 |
|---|---|
| `setup` | 在命令所在目录安装所选 agent 的 skill，并写入配置文件（默认 `~/.obsidian-wiki/config`） |
| `info` | 显示安装路径、版本与解析后的配置 |
| `list` | 列出内置 skill |
| `doctor` | 健康检查配置、vault 形态、bootstrap 资源与已安装 skill |
| `artifacts-create` | 为一次 skill 调用创建一个唯一的临时 artifacts 目录 |

```bash
obsidian-wiki setup --vault ~/brain
obsidian-wiki setup --list-agents          # 列出可选的 agent skill 目标
obsidian-wiki setup --vault ~/brain --knowledge-pack default --agent claude --agent codex
obsidian-wiki setup --vault ~/brain --knowledge-pack software-knowledge --agent claude,codex,pi
obsidian-wiki setup --vault ~/brain --knowledge-pack default --agent all  # 所有本地 agent 目标
obsidian-wiki setup --agent none       # 只配置 vault，不安装 agent skill
obsidian-wiki setup --list-knowledge-packs         # 列出 Knowledge Pack（Profile + Layout）
obsidian-wiki setup --vault ~/brain --knowledge-pack software-knowledge
obsidian-wiki setup --project /work/app  # 覆盖命令所在目录这一安装目标
obsidian-wiki setup --project-only       # 已废弃的空操作；setup 始终是项目本地安装
obsidian-wiki setup --copy             # 复制 skill 文件，而不是创建符号链接
obsidian-wiki setup --copy --skills-only --agent cursor  # 只写命令目录文件；不触碰 vault
obsidian-wiki setup --vault ~/brain --knowledge-pack default --refresh-knowledge-pack-marker  # 刷新同一个 Pack 的标记
obsidian-wiki setup --remote https://github.com/you/my-wiki.git   # 非交互式配置同步

obsidian-wiki doctor --json --pretty
obsidian-wiki doctor --vault /other/vault --project .
obsidian-wiki doctor --strict          # 有警告时也返回非零退出码
obsidian-wiki artifacts-create --workflow wiki-ingest --pretty
```

`artifacts-create` 返回的 JSON 包含唯一的 `run_id` 与一个位于操作系统临时目录下的绝对
`artifacts_dir`。一次调用及其子 workflow 复用该绑定；每个新的顶层调用都会创建另一个目录。因此运行
期产物不会落在已安装的 skill 目录里，连续运行也不会互相覆盖。

Setup 会把稳定的 Wiki context 一次性编译到 `OBSIDIAN_CONTEXT_SNAPSHOT` 指定的路径
（默认 `<vault>/_meta/context/wiki-context.json`）。之后的 context 解析会把该快照链接进调用的
artifacts 目录。当你更改 Knowledge Pack、owner rules、Writing Profile、taxonomy 或稳定元数据路径
后，请运行 setup/repair。

除 `setup` 与 `info` 外，其他命令都会在命令所在目录的安装已过期时给出警告（包已升级，但 skill 尚未
重新链接）。在该目录重新运行 `obsidian-wiki setup` 即可修复。

在终端中运行 setup 且未传 `--agent` 时，它会显示一个带编号的 agent 菜单，且没有默认选中项。非交互
式 setup 必须显式提供一个或多个 `--agent NAME`、逗号分隔列表、`--agent all`，或 `--agent none`；
它绝不会默默选择全部或全不选。每个 agent 目标都是项目本地的，默认落在运行 setup 的目录。

项目安装会把该选择应用到每一个生成的 agent 专属文件，而不只是 skill 目录。例如只选择 `claude` 会
创建 `.claude/skills/`、共享的 `AGENTS.md` 与 `CLAUDE.md`；它不会创建 Cursor、Windsurf、Kiro、
Antigravity、Copilot、Gemini 或 Hermes 的 bootstrap 文件。未选中 agent 的既有文件保持不动。

在终端中运行 setup 且未传 `--knowledge-pack` 时，它会列出可用的 Knowledge Pack，并要求你准确选择
一个编号或名称。Knowledge Pack 的选择从不接受列表。非交互式 setup 必须传 `--knowledge-pack NAME`；
它不会默默选择 `default`，也不会继承既有标记。

在终端中运行 setup 且未传 `--vault` 时，它会提示输入 vault 目录，并把当前目录的绝对路径作为默认值
显示。按 Enter 即接受该默认值。在非交互式运行中，setup 会保留已配置 vault 的回退；显式传
`--vault PATH` 可以覆盖它。

`--skills-only` 会把 setup 限制为命令目录内的 skill 与 bootstrap 安装。它不会读写配置目录、Writing
Profile、vault、Knowledge Pack 标记或 Git 集成。由于该模式没有其他 setup 工作，它要求显式指定
agent 选择。

对于已初始化的 vault，请选择与 `_meta/knowledge-pack.json` 中记录相同的 Knowledge Pack。选择不同的
Pack 不会绕过迁移安全：setup 会直接失败，而不是切换契约。旧版标记结构与过去的 `_meta/layout.json`
路径都不再被接受；在使用新 Pack 契约前，请重新初始化或执行显式迁移。

在对当前生效的 Knowledge Pack 做出有意的契约更新之后，请把 `--refresh-knowledge-pack-marker` 与该
同一个 Pack 的 `--knowledge-pack` 名称一起传入。它只刷新标记哈希；它无法切换 Pack 名称，切换需要
内容感知的迁移。

## 查询与 lint

| 命令 | 作用 |
|---|---|
| `query <question>` | 从已配置 vault 的索引回答问题 |
| `lint [vault]` | 发现缺失的 frontmatter、失效链接、重复页面与孤立页面 |

```bash
obsidian-wiki query "what do I know about MCP security?"
obsidian-wiki query "rate limiting" --top 12 --max-read 5 --json

obsidian-wiki lint                     # 使用已配置的 vault
obsidian-wiki lint /path/to/vault --strict
obsidian-wiki lint @research --json    # 只用 <配置目录>/config.research
obsidian-wiki lint --strict-trust      # trust ledger 出问题时直接失败，而不只是警告
obsidian-wiki lint --allow-lifecycle active --allow-relationship-type synthesizes \
  --required-trust-field updated --schema-source /path/to/vault/AGENTS.md
```

Lint 会同时解析 vault 与 schema：显式路径（不继承配置）、位置参数 `@name`、最近的 CWD `.env`，最后
是配置文件。CLI 的 schema 参数会扩展/替换该 vault 的解析结果，并记录在 JSON 的 `schema` 块中。

## 校验页面与来源

| 命令 | 作用 |
|---|---|
| `validate [vault] --pages PATH...` | 检查指定的 vault 相对路径页面是否满足当前 page contract |
| `verify [vault] --sources PATH...` | 检查某个 ingest 批次的来源是否已体现在 vault 与 manifest 中 |
| `verify-sections <structure.json>` | 把 PageIndex 的 `_structure.json` 与其计划覆盖的页面对照 |

```bash
obsidian-wiki validate --pages concepts/rate-limiting.md entities/nginx.md --json
obsidian-wiki validate --from-stdin --pretty < changed-pages.txt
obsidian-wiki verify --sources ~/research/a.md ~/research/b.md
obsidian-wiki verify-sections /tmp/pageindex/_structure.json --pages concepts/example.md
```

三者都支持 `--json` 与 `--pretty`，并像 `lint` 一样解析 vault。`validate` 与 `verify` 支持
`--from-stdin`；`verify-sections` 的 `--pages` 仅作为覆盖度提示。

## Context pack

`wiki-context-pack` 从既有 Markdown 编译出任务范围内的快照。笔记不需
要被移动到 wiki 生成的目录中，也不需要迁移到完整 frontmatter schema。流程是 read-only。

```bash
obsidian-wiki context-pack "authentication architecture" --budget 8000
obsidian-wiki context-pack --recent --budget 4000
obsidian-wiki context-pack "release notes" --budget 8000 --public-only
```

省略 `--budget` 会使用预设的 8000 个估算 token。

输出包含 source paths、summaries、选定 excerpts，以及一个硬性的估算 token 上限。Vault excerpts 会明确标成 untrusted reference data：
下游 agent 可以使用其中的事实，但不得执行笔记内嵌的指令。想要最小的 pack 请用
`--metadata-only`，需要工具间对接则用 `--json`。

| 参数 | 效果 |
|---|---|
| `--budget N` | 最大估算输出 token，256–100000（默认 8000） |
| `--recent` | 选取最近更新的笔记——这是唯一可以省略主题的方式 |
| `--public-only` | 排除 `visibility/internal` 与 `visibility/pii` 的笔记 |
| `--metadata-only` | 只输出标题、来源信息与摘要，不含正文摘录 |
| `--json` | 供工具间对接的结构化输出 |
| `--vault PATH` | 覆盖 `OBSIDIAN_VAULT_PATH` |

`context` 是 `context-pack` 的可用别名。

## Session brain

在 agent 会话历史之上构建主题图谱。输出是一个 **sidecar**，位于 `~/.claude/session-brain/`——绝不
写入 vault。详见 [Session Brain](session-brain.zh-CN.md)。

| 命令 | 作用 |
|---|---|
| `sessions-build` | 构建（或增量更新）主题图谱 |
| `sessions-query <topic>` | 找出与某主题最相关的会话 |
| `sessions-show <id>` | 显示某个会话的节点及其最近邻居 |
| `sessions-clusters` | 列出已发现的主题簇 |
| `sessions-name --from FILE` | 为主题簇分配可跨重建保留的名称 |

```bash
obsidian-wiki sessions-build                       # 冷启动约 3 秒，增量不到 1 秒
obsidian-wiki sessions-build --full --verbose      # 忽略缓存，重新读取全部会话
obsidian-wiki sessions-build --since 2026-01-01 --skip archived,scratch
obsidian-wiki sessions-build --k 12 --min-sim 0.12 --mutual --half-life 60

obsidian-wiki sessions-query "prismor telemetry"
obsidian-wiki sessions-query "auth bug" --project my-app --cluster 3 --json

obsidian-wiki sessions-show 01935a40 --neighbors 12
obsidian-wiki sessions-clusters --unnamed
obsidian-wiki sessions-name --from names.json      # 或传 - 从 stdin 读取
```

`sessions-name` 接收一个 JSON 数组，元素形如 `{"id": N, "name": "...", "summary": "..."}`。
`/session-brain` skill 会为你生成它。

## Vault 同步

| 命令 | 作用 |
|---|---|
| `sync` | 暂存、提交并推送 vault 中待处理的变更 |
| `sync-setup <remote>` | 配置 GitHub 同步（git init、`.gitignore`、remote） |

```bash
obsidian-wiki sync
obsidian-wiki sync-setup https://github.com/you/my-wiki.git
```

见 [Configuration → 把 vault 同步到 GitHub](configuration.zh-CN.md#把-vault-同步到-github)。

## Trust ledger

记录并校验经人工批准的置信度复核，让你可以在 CI 中把关「确实有人检查过这些页面」。

| 命令 | 作用 |
|---|---|
| `trust-record` | 记录显式批准的置信度人工复核 |
| `trust-check` | 对照 ledger 校验置信度值与材料指纹 |

```bash
obsidian-wiki trust-record --all --reviewed-at 2026-07-30T10:00:00+00:00 --approved
obsidian-wiki trust-record --page concepts/rate-limiting.md --reviewed-at <ISO> --approved
obsidian-wiki trust-check --strict
obsidian-wiki trust-record @research --all --reviewed-at <ISO> --approved --allow-lifecycle active
obsidian-wiki trust-check @research --allow-lifecycle active --schema-source /vault/AGENTS.md
```

`--reviewed-at` 必须带时区。`--approved` 是必填且强制的——它代表你的断言：所有被记录的置信度值都已
经人工批准。`trust-check --strict` 是 CI/定时任务用的门禁。`trust-record` 与 `trust-check` 解析与
lint 相同的 vault 范围 schema；记录与校验时要传同样的 lifecycle 与 required-field 覆盖值。如果
owner schema 不要求 `base_confidence`，缺少该字段的页面会被报告为 `not_applicable`，被
`trust-record --all` 排除，任何过期的 ledger 条目会先由 `trust-check` 警告，再由
`trust-record --page` 或一次重建移除。JSON 与人类可读的记录输出都会列出被排除的页面与被移除的过期
条目；人类可读输出在发生移除时还会向 stderr 输出警告。required-field 配置只接受
`base_confidence`、`lifecycle`、`lifecycle_changed` 与 `updated`；拼写错误会直接失败关闭。Lifecycle、
relationship-type 与 required-field 的覆盖值都会被去除首尾空白，空值或纯空白项会被拒绝，而不会加入
白名单。未显式传 `--schema-source` 时，针对显式 vault 的 CLI 覆盖会标记为 `cli:explicit-vault`；
CLI 与配置同时覆盖时使用 `cli+config:<resolved-config-path>`。

## 底层命令

供自动化、脚本与调试使用。skill 会在内部调用其中的一些命令。

| 命令 | 作用 |
|---|---|
| `graph-query <vault> <question>` | 只读 wikilink 索引回答问题，不打开页面正文 |
| `graph-analyse <vault>` | 枢纽节点、社区、意外连接——纯 Python，无额外依赖 |
| `graph <vault> <subcommand>` | NetworkX 图谱查询：`paths`、`neighbors`、`centrality`、`tag-subgraph`、`communities`、`stats`（需要 `pip install obsidian-wiki[graph]`） |
| `batch-plan <vault> <source_dir>` | 把来源目录拆成可并行摄取的批次，并跳过未变更文件 |
| `cache-check <vault> <sources...>` | 相对 `.manifest.json` 判断哪些来源是新增 / 已修改 / 未变更 |
| `cache-update <vault> <source>` | 摄取后把来源的 SHA-256 记入 `.manifest.json` |
| `cache-hash <path>` | 计算文件或目录哈希（不读写 manifest） |
| `text-chunk-plan <source>` | 为单个受支持文本来源规划确定性、穷尽的 UTF-8 字节区间 |
| `text-chunk-strategies` | 列出内置、已注册与已安装的自定义分块策略 |
| `text-chunk-read <source>` | 校验来源哈希，并物化恰好一个已规划的字节区间 |
| `text-document-plan <source>` | 把所有受支持来源规范化为 manifest 支撑的 ingest document；小文件产出 1 个，大文件产出多个 |
| `text-document-read <plan>` | 校验并物化恰好一个已规划的 ingest document |
| `text-document-commit <plan>` | 把一个已验证的 ingest document 原子记入 `.manifest.json` |
| `text-ingest-plan <source>` | 可恢复的 `wiki-folder-ingest`：创建或续跑一个仅含元数据的 text-ingest Job |
| `text-ingest-status <job>` | 报告确定性的 source/unit 计数、下一个 unit 与当前完成状态 |
| `text-ingest-extract <job>` | 用有界的隔离 `claude -p` worker 池处理符合条件的 Packet unit |
| `text-ingest-report <job>` | 由 Job 与 manifest 事实生成配套的 JSON 与 Markdown 完成报告 |
| `text-ingest-packet-check <job> <packet>` | 在页面归并前校验 Packet 的 Job/source/unit/path 绑定 |
| `text-ingest-unit-advance <job> <packet>` | 页面校验通过后，原子推进一个已验证的 direct 或 staged unit |
| `text-ingest-inline-check <job>` | 在不创建 Packet 的情况下校验已规划的整源 inline unit 与当前来源哈希 |
| `text-ingest-inline-advance <job>` | 页面校验通过后，原子推进一个重新验证过的 inline unit |
| `wiki-context-resolve` | 运行内置的 workflow context 解析器，不依赖当前目录 |
| `wiki-setup-contract-build <phase>` | 由内置模板与 Knowledge Pack 构建 setup 契约 |
| `wiki-knowledge-pack-apply` | 应用内置 Knowledge Pack，不依赖当前目录 |
| `wiki-route-resolve` | 通过内置的确定性布局路由器解析已声明的 page type |
| `ast-extract <path>` | 从代码中提取类、函数与 import——无 LLM，无 API 调用 |

```bash
obsidian-wiki graph-query /path/to/vault "transformer architecture" --pretty
obsidian-wiki graph-analyse /path/to/vault --top 30 --pretty
obsidian-wiki graph /path/to/vault centrality --method pagerank --top 20 --pretty
obsidian-wiki graph /path/to/vault paths --from concepts/rate-limiting --to entities/nginx --max-len 4
obsidian-wiki graph /path/to/vault neighbors concepts/rate-limiting --radius 2 --pretty
obsidian-wiki graph /path/to/vault stats --pretty
obsidian-wiki batch-plan /path/to/vault ~/research --max-mb 4 --max-files 30
obsidian-wiki cache-check /path/to/vault ~/research/*.pdf
obsidian-wiki cache-update /path/to/vault ~/research/paper.pdf --pages concepts/attention.md
obsidian-wiki text-chunk-plan ~/research/large.md \
  --chunk-strategy adaptive_sections --min-budget 24000 --pretty
obsidian-wiki text-chunk-strategies --pretty
obsidian-wiki text-chunk-read ~/research/large.md \
  --start-byte 0 --end-byte 47231 --expect-hash sha256:9e9f...
obsidian-wiki text-document-plan ~/research \
  --vault ~/brain \
  --target-budget 48000 --min-budget 24000 --hard-budget 64000 \
  --chunk-strategy adaptive_sections --strategy-options-file /tmp/chunk-options.json \
  --output /tmp/document-plan.json --pretty
obsidian-wiki text-document-read /tmp/document-plan.json --document-id doc-...
obsidian-wiki text-document-commit /tmp/document-plan.json \
  --document-id doc-... --created-page concepts/example.md --pretty

# 可恢复的 wiki-folder-ingest Job/Packet 命令
obsidian-wiki text-ingest-plan ~/research --vault ~/brain --output /tmp/job-plan.json --pretty
obsidian-wiki text-ingest-status ~/brain/_meta/ingest-jobs/<job-id> --pretty
obsidian-wiki text-ingest-extract ~/brain/_meta/ingest-jobs/<job-id> \
  --max-workers 4 --worker-timeout-seconds 3600 \
  --output /tmp/packet-extraction-report.json --pretty
obsidian-wiki text-ingest-report ~/brain/_meta/ingest-jobs/<job-id> \
  --output /tmp/job-completion.json \
  --markdown-output /tmp/folder-ingest-completion.md --pretty
obsidian-wiki text-ingest-packet-check ~/brain/_meta/ingest-jobs/<job-id> packets/<packet>.json
obsidian-wiki text-ingest-unit-advance ~/brain/_meta/ingest-jobs/<job-id> packets/<packet>.json \
  --mode staged --artifact _staging/concepts/example.md
obsidian-wiki text-ingest-inline-check ~/brain/_meta/ingest-jobs/<job-id> \
  --source-id <source-id> --unit-id <unit-id>
obsidian-wiki text-ingest-inline-advance ~/brain/_meta/ingest-jobs/<job-id> \
  --source-id <source-id> --unit-id <unit-id> --mode direct
obsidian-wiki wiki-setup-contract-build core --output-dir /tmp/wiki-setup
obsidian-wiki wiki-knowledge-pack-apply --knowledge-pack default --vault ~/brain --output-dir /tmp/wiki-setup
obsidian-wiki wiki-route-resolve --routing page-contract.json \
  --page-type concept --slug example
obsidian-wiki ast-extract ./src --pretty
```

`wiki-knowledge-pack-apply --knowledge-pack <name>` 选择一整套 Knowledge Pack。它的 `profile.json`
定义语义层面的目的、范围、提取、验证、新鲜度与检索契约；它的 layout 与 routing 文件定义物理路径。
`_meta/knowledge-pack.json` 为两侧绑定哈希，因此修改 `profile.json` 需要显式的同 Pack 标记刷新，或
一次内容感知的迁移。在对当前生效的 Pack 做出有意的契约更新后，用
`wiki-knowledge-pack-apply --refresh-knowledge-pack-marker` 刷新既有 vault；该参数无法切换 Pack
名称。

`text-chunk-plan` 接受以 UTF-8 或带 BOM 的 UTF-8 编码的 `.md`、`.markdown`、`.mdx`、`.txt` 与
`.rst`。`--target-budget` 默认 48,000 字节，`--min-budget` 默认目标值的一半，`--hard-budget` 默认
64,000 字节；后者是文档化的安全上限，也是每个已规划 unit 的绝对上限。默认的 `adaptive_sections`
策略会合并相邻的短段落；`strict_sections` 保留「每个标题一个 unit」的切分方式。
`--strategy-options` 接受内联 JSON 对象，`--strategy-options-file` 接受同一对象来自文件。要突破硬
上限，必须显式使用 `--allow-unsafe-hard-budget` 覆盖。`text-chunk-read` 会原样写出该区间、不额外
添加换行，并在来源在规划之后发生变化时失败。

`text-document-plan` 是 `wiki-ingest` 的规划器。它对每个文件应用同一套确定性分块器，查询
`.manifest.json`，并且只输出元数据。父 Agent 逐个处理待完成的 document：串行派发一个
`general-purpose` subagent 去执行 `/wiki-ingest-document`；该 subagent 拥有全新上下文，写入被串行化。
`text-document-read` 在返回某一个精确区间前会重新校验整个 Source File 的哈希，而
`text-document-commit` 在原子记录完成前会重复该检查。因此失败的 subagent 不会留下 manifest 记录，
下次运行会自然重试。轻量路径不创建 Job、unit 状态机、Packet、提取转储或持久 worker 目录，也不调用
`claude -p`。

`text-ingest-*` 命令实现可恢复的 `wiki-folder-ingest` Job/Packet 路径。`text-ingest-extract` 动态
填充一个有界 worker 池（默认 4，硬上限 32），原子地认领并完成 Packet unit，并通过隔离的
`claude -p --dangerously-skip-permissions --no-session-persistence` 进程直接调用
`/wiki-source-text`，且禁用 Agent 与 Task 工具。它从不使用 shell，
为每次尝试分配独立的 worker 目录并放入包内当前的 `wiki-source-text` skill，丢弃进程的
stdout/stderr，只信任磁盘上已规划的 Packet 与 `packet-validation.md`。因此危险的权限绕过被限制在
一个已经过校验的 Job 边界内。每个符合条件的 unit 在一次调用中最多运行一次；失败或中断的 unit 保持
可恢复。
`text-ingest-status`、`text-ingest-report`、`text-ingest-packet-check` 与 `text-ingest-inline-check`
对 vault 而言都是只读的。`text-ingest-report` 只写它被要求的 artifact，直接从当前 vault 推导
exact-hash manifest 覆盖度，并把 cross-linking 视为可选的后处理，而不是 Job 完成的一部分。
对应的 advance 命令在原子改变恰好一个 unit 之前，会重新校验它的 Packet 或 inline 来源绑定；staged
模式要求至少一个 `--artifact`，并且从不增加 integrated 计数。这些命令把确定性协调留在代码里，同时
Packet 提取可以并发进行，而所有页面归并仍然是串行的。`wiki-folder-ingest` 从解析后的 vault 配置中
取出生效的阈值、预算、策略与选项，并冻结进 Job；chunk 兼容字段也会保留在已完成的 manifest 条目中。

### 自定义文本分块策略

受信任的扩展包在它的 `pyproject.toml` 中注册一个 entry point：

```toml
[project.entry-points."obsidian_wiki.text_chunk_strategies"]
my_sections = "my_wiki_extension.chunking:pack_sections"
```

目标是一个满足以下契约的可调用对象：

```python
from collections.abc import Iterable
from obsidian_wiki.text_chunker import ChunkStrategyContext, TextBlock

def pack_sections(
    blocks: Iterable[TextBlock], context: ChunkStrategyContext
) -> Iterable[Iterable[TextBlock]]:
    # Stream groups in source order. This example deliberately emits one block per unit.
    for block in blocks:
        yield (block,)
```

该可调用对象必须把收到的每个 block 恰好一次、且按原顺序返回。每个分组都必须不超过
`context.hard_budget`，而带 `forced:` 标记的 block 必须保持独立。规划器在持久化 Job 之前会校验这些
不变量。`WIKI_TEXT_CHUNK_OPTIONS` 中的选项可通过 `context.options` 取得。嵌入式调用方也可以在调用
`plan_text_chunks()` 之前使用 `register_chunk_strategy()`。

`wiki-context-resolve`、`wiki-setup-contract-build`、`wiki-knowledge-pack-apply` 与
`wiki-route-resolve` 会在已安装的包或源码检出中定位各自的辅助脚本与内置资源。因此 workflow 不依赖
`.cac/...` 路径，也不依赖调用者的当前工作目录。带有 `{"mode":"config"}` 的 `vault-input.json` 会让
`wiki-context-resolve` 加载 wiki-setup 配置的 vault：优先一个可选的 Named Vault Profile（`profile`），
否则取包含 `OBSIDIAN_VAULT_PATH` 的最近 `.env`，再否则取配置文件。配置目录默认为 `~/.obsidian-wiki`，
可用 `OBSIDIAN_WIKI_CONFIG_DIR` 迁移。显式批准的 vault
路径使用 `{"mode":"interactive","vault_path":"/absolute/path"}`。

大多数命令都接受 `--json` 与/或 `--pretty`，以输出机器可读结果。
