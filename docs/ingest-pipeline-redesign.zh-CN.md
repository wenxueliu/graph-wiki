[English](ingest-pipeline-redesign.md) | 简体中文

# Text Ingest Pipeline V1 设计

状态：**V1 已实现（`wiki-folder-ingest` 与 `wiki-ingest`）**

本文档仍然是可恢复 `wiki-folder-ingest` Job/Packet 流水线的契约。另一个不需要 workflow 的
`wiki-ingest` skill 提供轻量替代方案：每个 Source File 都被规范化为一个或多个独立 document，每个
document 由一个由父 Agent 派发的、全新上下文的 `general-purpose` subagent 按串行顺序处理，并直接提交
到 `.manifest.json`。

实现对应关系：

- 确定性分区：`obsidian_wiki/text_chunker.py`；
- 最小 Job 与 Packet 契约：`obsidian_wiki/ingest_pipeline.py`；
- CLI 物化边界：`text-chunk-plan`、`text-chunk-read`、`text-chunk-strategies`；
- 轻量 document 规范化：`text-document-plan`、`text-document-read`、`text-document-commit`；
- 可恢复 Job 生命周期：`text-ingest-plan`、`text-ingest-status`、`text-ingest-extract`、
  `text-ingest-report`、`text-ingest-packet-check`、`text-ingest-unit-advance`、
  `text-ingest-inline-check`、`text-ingest-inline-advance`；
- 编排与提取：`wiki-folder-ingest` 与 `wiki-source-text`；
- 轻量 document 派发：父 Agent 对 `wiki-ingest-document` 的 `Task` 调用；
- 串行归并：`wiki-packet-integrate`。

## 1. 决策摘要

Version 1 只支持文本文档。它把文件夹编排、确定性文本分区、逐部分提取与 wiki 归并分离开来，因此一个
文件夹或一份大文档永远不必塞进单个 agent 上下文。

获准的方向是：

- 在本 repo 中本地实现文本分区；
- 把分区暴露为一个独立、可复用的 Python 特性；
- 不把 PageIndex 作为 V1 运行时依赖；
- 保留 PageIndex 作为未来可能的 PDF structure provider；
- 对每种不支持的格式显式路由，而不是尝试兜底；
- 在 V1 中保持中间契约与 job 状态最小。

## 2. V1 范围

### 支持的输入

| 扩展名 | 解释方式 |
|---|---|
| `.md`、`.markdown`、`.mdx` | 类 Markdown 文本，按标题感知分区 |
| `.txt` | UTF-8 纯文本，按段落感知分区 |
| `.rst` | reStructuredText，按 section 感知分区 |

V1 接受 UTF-8 与带 BOM 的 UTF-8。无效编码会以可操作的错误报告；自动猜测编码推迟。

### V1 中显式不支持

- PDF 与扫描文档；
- Word、PowerPoint、电子表格与 OpenDocument 文件；
- JSON、JSONL、CSV、XML、YAML 及其他结构化数据；
- 日志、聊天导出、会议记录与邮件归档；
- HTML 与网页 URL；
- 图像、音频与视频；
- 压缩包与可执行文件；
- 源代码文件与代码仓库。

不支持的输入会在文件夹报告中保持可见，带路径、检出类型与原因。它们绝不能被默默跳过或被重新解释为
纯文本。

## 3. 架构

```text
文件夹或文本文件
        |
        v
wiki-folder-ingest
  发现、哈希、分类，创建 job
        |
        v
独立的 text-chunker
  产出确定性的来源区间
        |
        v
有界的 claude -p worker 池 + wiki-source-text skill
  一个由 coordinator 指定的区间 -> 一个有界 Packet
        |
        v
wiki-packet-integrate
  把 Packet 串行归并进 wiki
        |
        v
确定性的 Job 完成报告

可选的后置步骤：cross-linker
```

文件夹 coordinator 只能看到路径、哈希、区间元数据、状态与 artifact 路径。它从不读取或接收完整的
来源正文。

## 4. 组件职责

### 4.1 `wiki-folder-ingest`

- 解析 vault 配置与 owner 约定；
- 递归发现文件，并应用既有的跳过目录规则；
- 把每个文件分类为受支持文本或不支持；
- 计算 SHA-256，跳过未变更的受支持来源；
- 创建一个持久化 Job，每个文件一条 source 记录；
- 对每个变更的文本来源调用 partition planner；
- 把小于等于已配置 direct-extraction 阈值的来源路由到串行 inline 归并，同时保留一个逻辑的
  整源 unit；
- 把每个较大来源的各部分调度进一个有界的隔离 `claude -p` 池，池直接调用 worker-only 的
  `/wiki-source-text` skill；
- 把 Packet 与 inline transport 排入串行的 `wiki-packet-integrate` 归并；
- 依据当前 Job 与 manifest 事实，为 complete、incomplete、unchanged、unsupported 与 failed 来源
  生成配套的 JSON 与 Markdown 报告。

它绝不能读取完整来源正文、提取知识、起草 wiki 页面，或直接推进永久 source manifest。

### 4.2 独立的 `text-chunker`

分区器是确定性基础设施，不是 Agent Skill。它属于一个可复用的 Python 模块，暂定为
`obsidian_wiki/text_chunker.py`。

它校验编码、扫描结构、寻找语义边界、强制执行硬预算、产出行与字节区间、物化一个被请求的区间，并报告
强制切分。它不做摘要、不做推断、不调用模型、不创建 Packet，也不知道 vault 的存在。

### 4.3 `wiki-source-text`

这个 worker-only skill 每次处理一个由 coordinator 指定的 packet-transport 来源区间。Coordinator 会为
每个活动槽位启动一个隔离的 `claude -p` 进程，只把规范的 Job 目录、source ID 与 unit ID 传给
`/wiki-source-text`。该 skill 只通过分区器读取那个区间，提取带精确 provenance 的有界知识，校验一个
Packet，并只返回一个有界交接。它不读取其他区间、不写 wiki 页面、不更新共享 Job 或 manifest 文件，也
不自己派生 worker 或派生嵌套 subagent。该进程只在经过校验的 Job 边界内使用
`--dangerously-skip-permissions`，并禁用会话持久化。Worker 启动或校验失败会让该 unit 停留在可续跑的
失败状态。

### 4.4 `wiki-packet-integrate`

`wiki-packet-integrate` 处理一个串行 transport 事务：

1. 校验一个 Packet，或校验并直接提取一个已规划的 inline 整源 unit；
2. 定位相关的既有页面；
3. 归并知识并记录矛盾；
4. 创建或更新页面，带 frontmatter、provenance、relationships 与 links；
5. 校验变更过的页面；
6. 页面校验通过后，把该 Packet 或 inline unit 标记为已归并；
7. 把来源级 finalization 候选返回给 `wiki-folder-ingest`。

Packet 与 inline transport 按来源顺序串行归并。Inline 提取留在 worker 上下文中，不创建 Packet 文件。
Wiki 充当增量 reducer；V1 不额外增加一个整文档 Reduce 阶段。

Job 在 exact-hash 来源收尾与确定性报告之后结束。Cross-linking 是可选的后续 workflow，绝不改变 ingest
Job 是否完成。

## 5. 独立的文本分区特性

### 5.1 公开 Python 接口

```python
def plan_text_chunks(
    source: Path,
    *,
    target_budget: int = 48_000,
    hard_budget: int = 64_000,
) -> ChunkPlan: ...

def read_text_chunk(source: Path, unit: ChunkUnit) -> str: ...
```

`target_budget` 是偏好的打包大小。`hard_budget` 是绝对的 UTF-8 字节安全上限，而不是声称的精确模型
token 数。该模块必须可在不导入 vault、manifest 或 LLM 代码的情况下复用。

### 5.2 预算模型

精确 tokenization 取决于模型，且可能需要可选依赖。V1 使用：

- 当有兼容计数器时，用估算 token 数做报告；
- 用 UTF-8 字节长度作为强制的、无依赖的硬限制。

对于基于字节的 tokenizer，token 数不会超过输入字节数。因此 64,000 字节的上限在保守情况下仍远低于
200k token 上下文，为指令、相关 wiki 页面、推理与输出预留了空间。配置可以调低这些默认值。把它们提高到
已文档化的安全上限之上，需要用户显式覆盖。

### 5.3 流式扫描

Planner 以二进制模式增量读取，并解码完整的 UTF-8 序列。它追踪：

- 从零开始的字节起点与独占字节终点；
- 从一开始的起止行号；
- 当前 heading path；
- 结构块类型；
- UTF-8 字节大小；
- 可选的估算 token 数。

它绝不执行无界的整文件 `read()`。内存占用与最大的结构块成正比，而不是与整份文档成正比。

### 5.4 结构边界

偏好边界，按顺序：

1. 文档 section；
2. 由空行分隔的段落；
3. 完整的 Markdown 块，例如列表、表格与围栏代码；
4. 完整的行；
5. 单行过大时的 UTF-8 安全字符边界。

Markdown 侦测识别 ATX 标题，并忽略围栏代码内的标题。RST 侦测识别常见的下划线/上划线 section 样式。
纯文本依赖段落，除非侦测到明确的 section 模式。

### 5.5 打包与切分

相邻小块会累积，只要该 unit 仍在 `target_budget` 及以下。打包不会跨越顶层 section 边界，除非相邻
section 能够放下且其边界仍在元数据中被表示。

如果一个 section 超过 `hard_budget`，就递归切分：

```text
section -> paragraphs -> block/list items -> lines -> UTF-8-safe characters
```

代码围栏与表格在放得下时保持完整。超大的块在行边界处切分，并被标记，例如：

```json
{
  "forced_split": true,
  "split_reason": "oversized_code_fence"
}
```

单个过大的行只在合法的 UTF-8 字符边界处切分，并标记为 `oversized_line`。

### 5.6 边界上下文

自然边界不需要重叠。强制切分会保留 heading path，并可能暴露一个小的、单独标记的 context hint。
Context hint 不是覆盖，绝不能被当作新论断提取。V1 偏好不做原始重叠，除非测试证明有实质的质量损失。

### 5.7 不保留持久化 chunk 副本

Planner 存储区间，而不是把内容复制进临时 Markdown 文件。`read_text_chunk()` 定位到字节区间，校验
期望的来源哈希，解码它，并只返回那个 unit。这避免了敏感数据被重复，也避免了意外的 wiki 索引。

### 5.8 Chunk plan schema

```json
{
  "chunk_plan_version": 2,
  "chunker_version": 2,
  "source": {
    "path": "/data/large-document.md",
    "content_hash": "sha256:9e9f...",
    "encoding": "utf-8",
    "size_bytes": 3812042,
    "line_count": 48219
  },
  "budget": {
    "mode": "utf8_bytes",
    "target": 48000,
    "min": 24000,
    "hard_max": 64000
  },
  "chunking": {
    "strategy": "adaptive_sections",
    "options": {}
  },
  "units": [
    {
      "unit_id": "unit-0001",
      "heading_path": ["Part I", "Background"],
      "heading_paths": [["Part I", "Background"], ["Part I", "Motivation"]],
      "start_line": 1,
      "end_line": 318,
      "start_byte": 0,
      "end_byte": 47231,
      "size_bytes": 47231,
      "estimated_tokens": null,
      "forced_split": false
    }
  ]
}
```

不变量：

- unit 按来源位置排序；
- V1 中区间不重叠；
- 它们的并集恰好覆盖每个来源字节一次，可选的 BOM 除外；
- 没有 unit 超过 `hard_max`；
- 字节位置落在合法的 UTF-8 边界上；
- 行区间与字节区间一致；
- 相同输入、版本、预算、策略与选项产生相同输出；
- 如果来源哈希在规划之后发生变化，物化会失败。

### 5.9 稳定的 unit ID

Unit ID 在同一个来源版本内是确定性的：

```text
unit_id = sha256(chunker_version + source_hash + start_byte + end_byte)
```

一次编辑会创建新的来源版本，并可能移动之后的边界。跨任意编辑的内容定义式身份推迟。

## 6. PageIndex 评估与决策

PageIndex 不是 V1 的分区器，因为：

- 它的主要抽象是一棵分层检索树，宣称「No Chunking」；
- 它的 Markdown 支持只识别有限的标题集合；
- 它的 Markdown 处理会把整个文件读入内存；
- `--max-tokens-per-node` 只作用于 PDF 路径；
- 无标题的文本不会产生有用的 Markdown 树；
- 一个超大的 Markdown section 不会被递归按 token 切分；
- 目前导入它的 Markdown 路径会带来与 PDF、LiteLLM 相关的依赖；
- PDF 分组与递归细化针对的是树构建，而不是一个通用的硬分区契约。

V1 可以复用标题层级与来源定位符的想法，但不复用 PageIndex 运行时。

对于未来的 PDF 版本，PageIndex 可以位于一个 structure-provider adapter 之后：

```text
PDF -> PageIndex section/page tree -> 本地硬预算切分器 -> source units
```

PageIndex 提供语义边界建议；本地切分器对上下文限制仍然权威。失败时回退到有界的页面窗口，而绝不整文档
读取。

## 7. 最小 Job 契约

```text
$OBSIDIAN_VAULT_PATH/_meta/ingest-jobs/<job-id>/
├── job.json
└── packets/
    └── <source-id>-<unit-id>.json
```

只有 coordinator 写 `job.json`；worker 写各自不同的 Packet 路径。

```json
{
  "job_version": 1,
  "job_id": "20260826-143012-a81f",
  "source_root": "/data/notes",
  "status": "incomplete",
  "sources": [
    {
      "source_id": "src_a13f9c",
      "path": "/data/notes/large.md",
      "content_hash": "sha256:9e9f...",
      "kind": "markdown",
      "status": "processing",
      "chunk_plan": {
        "units_total": 12,
        "units_integrated": 6,
        "next_unit": "unit-0007"
      }
    },
    {
      "path": "/data/notes/report.pdf",
      "kind": "pdf",
      "status": "unsupported",
      "reason": "PDF processing is not available in V1"
    }
  ]
}
```

详细区间最初可以留在 `job.json` 中。如果真实 fixture 让计划过大，它们可以移至每个来源一个被引用的
plan 文件；V1 不会预先增加这一层。

## 8. 最小 Packet 契约

```json
{
  "packet_version": 1,
  "packet_id": "pkt_a13f9c_unit0001",
  "source": {
    "source_id": "src_a13f9c",
    "path": "/data/notes/large.md",
    "content_hash": "sha256:9e9f..."
  },
  "unit": {
    "unit_id": "unit-0001",
    "heading_path": ["Part I", "Background"],
    "start_line": 1,
    "end_line": 318,
    "start_byte": 0,
    "end_byte": 47231
  },
  "extracted": {
    "summary": "...",
    "concepts": [],
    "claims": [],
    "entities": [],
    "relationships": [],
    "questions": []
  },
  "warnings": []
}
```

V1 不增加 claim ID、Packet group、receipt、rename alias，也不增加单独的 coverage 文件。Job 中排好序的
unit 列表与状态就是覆盖记录。

## 9. 处理与会话隔离

对于一个或多个变更的来源：

1. 计算它的哈希；
2. 用 `text-chunk-plan` 生成有序区间；
3. 如果完整的非空来源小于等于 `WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES`，就用一个逻辑的整源 inline unit
   代替常规区间，且不分配 Packet 路径；
4. 从已规划的 Packet 路径重建被中断的 packet-transport `extracting` unit；
5. 动态认领不超过 `WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS` 个待处理 packet unit；
6. 为每个已认领的 packet unit 启动一个隔离的
   `claude -p --dangerously-skip-permissions --no-session-persistence` 进程，只传 Job 目录/source
   ID/unit ID，并直接调用 `/wiki-source-text`；
7. 让该 skill 运行 `text-chunk-read`，创建并校验一个独立 Packet，并只返回它的 Packet/报告路径加上
   有界的状态元数据；
8. 缓冲先于更早 unit 完成的 Packet；
9. 用 `wiki-packet-integrate` 按稳定的 source/unit 顺序串行归并 Packet 与 inline transport；inline
   提取留在内存中；
10. 标记每个已归并的 unit，并重新填充有界提取队列；
11. 只有在每个 unit 都归并之后，才记录永久 source 条目。

提取可以跨不同文档以及同一文档内的不同 unit 并发进行。配置的最大值默认是 4，宿主可能施加更低的上限。
V1 中归并保持串行，并遵循稳定的 source/unit 顺序。没有 worker 时，Job 会暴露下一个待处理 unit 供之后
的调用使用。

Direct-extraction 阈值默认是 16,000 UTF-8 字节，不得超过硬预算，并可用 `0` 禁用。它被冻结在 Job 中，
并参与未完成 Job 的续跑兼容性判断。

## 10. 增量处理与完成

`.manifest.json` 仍然是权威。一个文件只有在每个已规划 unit 都归并之后才算完成：

```json
{
  "path": "/data/notes/large.md",
  "content_hash": "sha256:9e9f...",
  "source_type": "text",
  "chunker_version": 2,
  "budget": {"mode": "utf8_bytes", "target": 48000, "min": 24000, "hard_max": 64000},
  "chunking": {"strategy": "adaptive_sections", "options": {}},
  "units_total": 12,
  "units_integrated": 12,
  "pages_produced": ["concepts/example.md"],
  "last_ingested": "2026-08-26T15:30:00+08:00"
}
```

规则：

- 哈希、chunker 版本、预算、策略与选项都匹配：未变更；
- 哈希变化：创建新计划并重新处理；
- 哈希匹配的未完成 Job：续跑下一个待处理 unit；
- 来源在规划后发生变化：作废待处理区间并重新规划；
- 不支持的来源：报告，但不添加永久 ingested 条目；
- 缺失来源：报告可能过期的页面，但绝不自动删除。

V1 用路径加内容哈希作为身份。重命名侦测推迟。

## 11. 已交付的 CLI

```bash
# 独立分区器（wiki-folder-ingest 也使用）
obsidian-wiki text-chunk-plan <source> --pretty
obsidian-wiki text-chunk-read <source> \
  --start-byte <N> --end-byte <N> --expect-hash sha256:<hex>
obsidian-wiki text-chunk-strategies --pretty

# 轻量 wiki-ingest 路径（无 Job，无 Packet）
obsidian-wiki text-document-plan <source>
obsidian-wiki text-document-read <plan.json> --document-id <id>
obsidian-wiki text-document-commit <plan.json> --document-id <id>

# 可恢复的 wiki-folder-ingest Job 生命周期
obsidian-wiki text-ingest-plan <source> --vault <vault>
obsidian-wiki text-ingest-status <job-dir>
obsidian-wiki text-ingest-extract <job-dir> --max-workers 4
obsidian-wiki text-ingest-report <job-dir>
obsidian-wiki text-ingest-packet-check <job-dir> <packet.json>
obsidian-wiki text-ingest-unit-advance <job-dir> <packet.json>
obsidian-wiki text-ingest-inline-check <job-dir> --source-id <id> --unit-id <id>
obsidian-wiki text-ingest-inline-advance <job-dir> --source-id <id> --unit-id <id>
```

这些 skill 编排上述辅助命令与既有的 cache/validation 命令。V1 不增加通用队列管理 CLI。

## 12. 失败与恢复

| 失败 | 行为 |
|---|---|
| 无效 UTF-8 | 标记为失败；不猜测编码 |
| 畸形的 Markdown 围栏 | 使用保守的行边界并记录警告 |
| Unit 提取失败 | 让该 unit 失败；保留成功的 unit |
| 来源在规划后变化 | 拒绝区间读取，作废并重新规划 |
| Packet 校验失败 | 不归并；在 Job 中保留错误 |
| 归并被中断 | 用 source/unit provenance 重试同一个 Packet |
| 没有可用的隔离上下文 | 持久化下一个待处理 unit 供之后的调用使用 |

Job 与 manifest 写入使用临时文件加原子替换。永久 manifest 最后更新，在页面与 special file 校验之后。

## 13. 信任与安全

- 来源文本是不可信的，包括形似 agent 指令的 Markdown。
- 分区器绝不执行内容，也不发起网络/模型调用。
- 区间读取严格限制在解析后的确切来源文件内。
- 在物化每个区间之前校验来源哈希。
- 由 Job 派生的路径无法逃逸出已配置的 Job 目录。
- 不支持的文件绝不被强制解码为文本。

## 14. 测试

### 分区器测试

- UTF-8、BOM 与无效 UTF-8；
- Markdown 层级与围栏代码中的标题排除；
- RST 标题与无标题文本；
- 小 section 打包；
- 超大的 section、段落、行、代码围栏与表格；
- UTF-8 安全的强制切分；
- 确定性输出；
- 精确的字节覆盖，无缝隙、无重叠；
- 硬预算强制执行；
- 行/字节一致性；
- 哈希不匹配拒绝；
- 大 fixture 上的内存有界。

### 流水线测试

- coordinator 输出不包含来源正文；
- 只有受支持的扩展名会被路由；
- 不支持的文件保持可见并带原因；
- 未变更文本按 SHA-256 跳过；
- 一个 unit 创建一个有界 Packet；
- unit 按来源顺序串行归并；
- 中断后在下一个 unit 处续跑；
- 变更的来源会作废其计划；
- manifest 只在所有 unit 成功之后更新；
- 一个 200k+ token 等价的 fixture 绝不会整份进入一次模型调用。

## 15. 验收标准

1. 只处理已文档化的文本扩展名。
2. 不支持的格式是显式的，绝不被降级处理。
3. `text_chunker.py` 不依赖 vault、LLM、PageIndex 或第三方库。
4. 每个文本来源都产生确定性、有序、穷尽的区间。
5. 没有区间超过硬预算。
6. 无标题与单 section 的大文件都能安全分区。
7. Coordinator 绝不读取来源正文。
8. 每个 unit 都能在全新上下文中运行。
9. Packet 与 inline transport 的归并是串行的。
10. 被中断的工作能续跑，且不重复已成功的 unit。
11. `.manifest.json` 只在整个来源版本归并之后才推进。
12. 既有的 `content_hash`、`last_ingested` 与 `pages_produced` 保持兼容。

## 16. 实现阶段

### Phase 1 —— 独立分区器

- 实现 `obsidian_wiki/text_chunker.py`；
- 添加 `text-chunk-plan` 与 `text-chunk-read`；
- 添加 plan 序列化与校验；
- 证明边界与预算不变量。

### Phase 2 —— 文本来源 skill

- 创建 `wiki-source-text`；
- 实现最小 Packet schema；
- 每次隔离调用处理一个 unit；
- 校验 Packet。

### Phase 3 —— 文件夹编排

- 创建 `wiki-folder-ingest`；
- 实现分类、最小 Job 与续跑行为；
- 在不读取内容的情况下路由 unit。

### Phase 4 —— 仅做归并的摄取

- 为文本 Packet 添加 worker-only 的 `wiki-packet-integrate`；
- 串行化归并与来源顺序更新；
- 把文件夹与原始来源读取留在公开的 `wiki-folder-ingest` 中；
- 保留文件/目录兼容性路由；
- 更新 manifest 完整性验证。

### Phase 5 —— 文档与清理

- 更新 architecture、skills、CLI、configuration 与 agent routing 文档；
- 在兼容性测试通过后移除过时的文件夹批处理；
- 记录不支持的格式与未来的扩展点。

## 17. 推迟的工作

- 基于 PageIndex 的 PDF 结构提取；
- Office、结构化数据、对话、日志、图像、网页与代码库 skill；
- 作为强制依赖的精确模型 tokenizer；
- 跨编辑的内容定义式 chunk 身份；
- 自动重命名侦测；
- claim 级稳定 ID；
- 通用队列管理 CLI；
- 独立的 coverage、receipt 与 error artifact 树；
- 跨所有 Packet 的整文档归约。

这些特性只有在 V1 fixture 证明存在具体需求之后才会加入。
