[English](viewer.md) | 简体中文

# 本地图谱查看器

`graph-wiki serve` 会启动一个只读 HTTP 服务，让你在浏览器里把 vault 当作图谱浏览。它是一个展示
层：页面读取 vault 索引，绘制力导向图；点击节点时显示页面的摘要、标签、链接与原始 Markdown。
它不会修改 vault。

查看器是给人用的。给 AI 检索时，请继续使用现有的
[`zvec` pack 索引与 CLI](#ai-检索仍然走-zvec-与-cli)；查看器不会增加第二套搜索引擎。

## 快速开始

```bash
graph-wiki serve --vault ~/brain
```

```text
graph-wiki viewer: http://127.0.0.1:8765/
vault: /home/you/brain
Ctrl-C to stop
```

打开该 URL，或加 `--open` 自动打开默认浏览器。

| 选项 | 默认值 | 作用 |
|---|---|---|
| `--vault PATH` | 解析后的配置 | 覆盖 `OBSIDIAN_VAULT_PATH`；支持 `@name` 选择器 |
| `--host HOST` | `127.0.0.1` | 绑定地址；`0.0.0.0` 会把 vault 暴露到你的网络 |
| `--port PORT` | `8765` | 绑定端口；`0` 表示自动选择空闲端口 |
| `--open` | 关闭 | 在默认浏览器中打开查看器 |
| `--verbose` | 关闭 | 打印每个 HTTP 请求 |

服务默认只绑定 loopback，且没有鉴权。如果你显式绑定非 loopback 地址，任何能访问该地址的人都能
读取这个 vault。

## 页面能看到什么

- **图谱。** 节点大小按去重后的邻居度数计算，颜色按 category。typed relationship 使用自己的颜色
  与箭头；普通 wikilink 保持灰色。关系标签可以开关。
- **收窄范围。** 搜索 title、slug、category、tags、summary 与 path；按 category 或 tag 过滤；
  用 **Typed only** 隐藏未标注类型的链接。顶部会显示当前可见的页面与链接数量。
- **详情侧栏。** 点击节点可以看到 category、tags、summary、入链/出链，以及原始 Markdown 预览。
  操作按钮可以在 Obsidian 中打开、聚焦该节点、复制深链，或复制页面 API URL。
- **深链。** `http://127.0.0.1:8765/?node=concepts/transformers` 会在图谱加载后选中对应页面。
  选中节点时 URL 会同步更新。
- **刷新。** **Refresh** 会重新检查 vault。服务按 `(path, mtime_ns, size)` 指纹缓存 payload
  一秒，未变化的文件不会被重新解析。

页面刻意不是编辑器。它不会把 Markdown 渲染成 HTML、不会写文件，也不会暴露目录列表。

## 端点

浏览器页面只需要以下路由：

| 路由 | 用途 |
|---|---|
| `GET /` | HTML 外壳与静态资源 |
| `GET /api/graph` | 页面使用的图谱 payload：节点、边、统计、vault 指纹 |
| `GET /api/page?id=<page-id>` | 页面 frontmatter、原始 Markdown 正文与 Obsidian URI |

`/api/page` 接受 `max_bytes` 来限制预览长度。`GET /api/graph` 与 `GET /api/page` 支持
`ETag` / `If-None-Match`。

节点 id 是去掉 `.md` 的 vault 相对路径（如 `concepts/transformers`）。每个节点同时保留
wikilink 的 `slug` 作为别名。如果两个文件共享同一个 slug，查看器会选择与来源页面同 category
的目标（否则选字典序最小的 id），并把该边标记为 `ambiguous: true`。

图谱 payload 带有 schema 版本：

```json
{
  "schema_version": 1,
  "generated_at": "2026-01-01T00:00:00+00:00",
  "vault": {
    "name": "brain",
    "path": "/home/you/brain",
    "fingerprint": "…"
  },
  "stats": {
    "pages": 42,
    "edges": 87,
    "typed_edges": 19,
    "untyped_edges": 68,
    "density": 0.0505,
    "categories": {"concepts": 20, "entities": 10},
    "tags": {"ml": 12},
    "isolated": []
  },
  "nodes": [
    {
      "id": "concepts/transformers",
      "slug": "transformers",
      "label": "Transformer Architecture",
      "title": "Transformer Architecture",
      "category": "concepts",
      "tags": ["ml", "architecture"],
      "summary": "The attention-based architecture introduced in Attention Is All You Need.",
      "path": "concepts/transformers.md",
      "tier": "core",
      "lifecycle": "active",
      "operational_state": "",
      "degree": 12,
      "in_degree": 5,
      "out_degree": 7
    }
  ],
  "edges": [
    {
      "id": "concepts/transformers|entities/vaswani|implements",
      "source": "concepts/transformers",
      "target": "entities/vaswani",
      "relation": "implements",
      "kind": "relationship",
      "typed": true,
      "weight": 1,
      "representations": ["relationships"],
      "ambiguous": false
    }
  ]
}
```

边按框架的 Edge Identity 去重：`(source, target, relation)`。指向同一目标的重复普通链接会合并成
一条 untyped 边，并累加 `weight`。

## AI 检索仍然走 zvec 与 CLI

查看器不是检索栈的替代品：

- `zvec` 是建立在不可变 pack chunk 之上的可选 BM25 + Jieba 全文索引。它回答“哪些 chunk 命中这个
  查询”，没有图谱边。
- `graph-wiki context-pack` 编译有界、带引用的上下文切片。
- `graph-wiki graph-query` 返回结构化候选、路径与 `should_read`。
- `graph-wiki graph-analyse` 报告枢纽、社区与意外连接。

如果 agent 能运行 CLI，就使用这些命令。查看器的 JSON 主要是页面自己的后端，不是稳定的 AI 检索
契约。这样只保留一套搜索引擎（zvec / pack 索引），而不是再加一套。

## 只读与安全

- 只接受 `GET` 与 `HEAD`；没有写入路由。
- vault 在内存中读取；查看器不会创建 `.obsidian/frontmatter-index.json`。
- 默认绑定 loopback。服务会把 `Host` 头与绑定的 loopback 主机比对，降低 DNS rebinding 风险。
- 静态资源路由是白名单。页面端点会把 id 解析成索引中的路径，并拒绝 vault 之外的路径。
- 响应使用严格的 `script-src 'self'` Content-Security-Policy。图谱库随包本地提供，因此可以离线
  使用，也不会发起外部请求。

## 与 `wiki-export` 的关系

`wiki-export` 写出静态产物（`graph.json`、`graph.html`、GraphML、Cypher、OKF），用于分享或交给
外部工具。`graph-wiki serve` 是实时、只读的：不写任何文件，刷新时反映 vault 的修改。需要把文件交给
别人时用导出器；想浏览时用查看器。

## 故障排查

- **端口已被占用。** 运行 `graph-wiki serve --port 0`；打印出的 URL 会包含实际端口。
- **图谱为空。** 确认 vault 在 `_raw/`、`_archives/`、`_readouts/` 等系统区域之外有 Markdown
  页面。访问 `/api/graph` 可以直接检查 payload。
- **页面缺失。** 查看器会排除任意位置的簿记文件（`index.md`、`log.md`、`hot.md`、
  `_insights.md` 以及 agent bootstrap 文件），以及根目录的 `README.md`。
- **Open in Obsidian 没反应。** 需要安装 Obsidian，并让系统注册 `obsidian://` 链接。按钮使用
  vault 的绝对路径。
- **大库初次布局较慢。** 力导向布局只运行一次，之后会关闭物理模拟。可以用搜索或过滤收窄图谱，
  只在需要时 Refresh。
