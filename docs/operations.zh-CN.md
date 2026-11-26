[English](operations.md) | 简体中文

# 运营指标

Wiki 可以内容正确，却没人使用、逐渐陈旧，或者无法判断该优先维护什么。运营指标回答质量闸门
回答不了的问题：哪些页面真的被打开、哪些发生了变更、哪些正在老化，以及哪些高访问页面应该
优先复核。

这一层**默认关闭**，并与 `quality` 相互独立。质量关心知识是否可信；运营关心 vault 如何被使用
和维护。

## 统计什么

统计单位是**知识页面**（当前 Knowledge Pack content roots 下的 Markdown 页面）。源文件仍由
`.manifest.json` 单独跟踪。

| 信号 | 含义 |
|---|---|
| 访问（view） | 人类打开了页面。从 Graph Viewer 与 Obsidian 插件采集；门户或网关也可以提交规范化事件。 |
| 检索（retrieval） | agent 或 CLI 命令返回了页面：`query`、`context-pack`、`graph-query`、`pack search`、`access search`、`access page`。 |
| 更新（update） | 页面内容哈希发生变化。报告区分 `created`、实质性 `updated`、`metadata_only`、`renamed` 与 `deleted`。 |
| 版本（version） | 每个页面派生出的计数器，只随实质性变更递增。它永远不会写进 frontmatter。 |
| 过期（expiry） | 两类独立信号：trust 台账的复核到期（沿用现有 review SLA）与老化（超过 `--aging-days` 没有实质性变更，默认 365 天）。 |
| 元数据健康 | `updated` 漂移、非法日期、日期倒挂，以及缺失 lifecycle/summary/sources。 |

frontmatter 中的 `updated:` 仍然是面向人的日期。变更历史使用内容哈希，因为日期可能被忘记、
手工修改，或者在内容没变时被抬高。

## 采集

### Graph Viewer

```bash
graph-wiki serve --ops --port 8765
```

Viewer 对携带浏览器页面生成的 `X-Viewer-Id` 请求头、且成功返回的 `/api/page` 响应记录一条
`view` 事件。`HEAD`、`304`、错误响应以及没有该请求头的请求都不计入，因此 curl、复制出去的
API 链接和 agent 不会虚增访问量。

### Obsidian

```bash
graph-wiki ops install-obsidian ~/brain --port 8765
```

内置插件把 `file-open` 事件发送到本地 Viewer 端点。它只支持桌面端：移动端 Obsidian 无法访问
运行在桌面上的 Viewer。如果迁移了状态目录，`serve` 与 `install-obsidian` 必须使用相同的
`--ops-dir`。

### Agent 与 CLI 检索

```bash
export GRAPH_WIKI_OPS=1
```

开启后，`query`、`context-pack`、`graph-query`、`pack search`、`access search` 与
`access page` 会记录它们返回的页面。agent 直接读取文件对本层不可见；只有这些命令会产生检索
事件。

### 门户与访问网关

单条事件用 `ops record`，批量用 `ops ingest`，或使用带 token 的 `POST /api/ops/event`。
典型的一行：

```json
{"event":"view","page":"concepts/transformers","source":"portal","client":"u-42","ts":"2026-11-26T10:42:10+08:00"}
```

`event` 为 `view` 或 `retrieval`，`page` 为不带 `.md` 的 vault 相对路径，`source` 是小写标签，
`client` 是不透明 id，`ts` 是带时区的 ISO-8601 时间（默认当前时间）。

## 状态布局

所有数据都位于 vault 外，默认在 `~/.graph-wiki/state/<vault-id>/ops/`：

```text
ops/
├── meta.json          # vault 身份与开始跟踪时间
├── inventory.json     # 当前页面元数据、哈希、版本
├── history.jsonl      # 追加式变更历史
├── events/            # YYYY-MM-DD.jsonl 访问与检索事件
└── token              # Obsidian 插件与事件端点使用的本地 token
```

目录以仅所有者可访问的权限创建。位于 vault 内的 ops 目录会被拒绝；`--save` / `--out` 也拒绝把
报告写进 vault。

## 命令

```bash
graph-wiki ops scan ~/brain
graph-wiki ops report ~/brain --days 30 --top 10
graph-wiki ops report ~/brain --json --pretty
graph-wiki ops report ~/brain --baseline "$STATE/ops-latest.json" --save "$STATE/ops-latest.json"
graph-wiki ops events ~/brain --days 2 --limit 20
```

`ops scan` 刷新清单并追加变更事件。`ops report` 默认先扫描；用 `--no-scan` 基于现有清单直接
出报告。报告包含：

- `views`：去重总量、原始总量、不同 client id 数、Top 页面、零访问与从未访问页面
- `retrievals`：按来源统计的总量与 Top 页面
- `updates`：created、实质性更新、仅元数据变更、重命名、删除，以及变更最多的页面
- `versions`：跟踪页面数、变更页面数与最大派生版本
- `expiry`：复核到期、即将到期与老化页面
- `metadata_health`：漂移与完整性警告
- `signals`：按优先级排列的动作建议，例如“高访问但复核已过期”

访问按页面、client 与 source 在 30 分钟窗口内去重（`--dedupe-minutes`）；原始事件仍会计入
`views.raw`。`views.viewers` 统计的是不同 client id，不是人数。

## 元数据维护

| 层 | 内容 | 写者 | 性质 |
|---|---|---|---|
| 语义元数据 | `title`、`category`、`tags`、`summary`、`sources`、`provenance`、`lifecycle`、`base_confidence`、`created`、`updated` | 写页面的 skill 与人工复核 | 权威 |
| 派生身份 | 哈希、版本、首次出现、最后变更 | `ops scan` | 可重建 |
| 运行事件 | 访问、检索、变更事件 | 各采集器 | 追加式 |

规则：

- 实质性变更时更新 `updated`；只改时间戳的编辑不要更新。
- 人工复核走 `trust-record`；运营层复用同一份台账与 SLA。
- 运营层从不修改页面，只报告漂移，由 agent 或人来修。
- 不要把 `view_count`、`last_viewed` 或 `version` 加进 frontmatter。这些值会过期，并会在多个
  写入者之间冲突。

## 隐私、保留与限制

- 不保存 IP、User-Agent、Referer、搜索词或页面正文。
- 事件端点需要 token，Viewer 默认只绑定回环地址。
- 状态是单机本地的。多台机器不会自动汇总；团队级采集需要共享网关或采集器。
- 版本历史只保存哈希与元数据，不保存正文，因此不能渲染 diff。
- agent 直接读取文件、以及未安装插件的 Obsidian 打开，都无法观测。
- 事件与报告只用于观测；`quality` 仍然是 CI 闸门。

## 另见

- [CLI 参考](cli.zh-CN.md#运营指标)
- [图谱查看器](viewer.zh-CN.md#运营记录)
- [知识质量](quality.zh-CN.md)
- [访问控制](access-control.zh-CN.md)
