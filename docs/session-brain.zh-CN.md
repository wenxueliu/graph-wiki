[English](session-brain.md) | 简体中文

# Session Brain

你的 agent 会话历史是一座你从来无法搜索的知识库。你知道自己以前解决过这件事，但你不知道那个 UUID。

Session brain 在这段历史之上构建一张主题图谱——包括每一份 Claude transcript，以及那些只作为
`history.jsonl` 中 prompt 保留下来的被修剪会话——让你能找到某件事发生在哪个会话。

```bash
graph-wiki sessions-build                      # 冷启动约 3 秒，增量不到 1 秒
graph-wiki sessions-query "prismor telemetry"  # 按相关性 × 新鲜度排序
graph-wiki sessions-show <session-id>          # 某个会话及其最近邻居
graph-wiki sessions-clusters                   # 已发现的主题
open ~/.claude/session-brain/graph.html           # 交互式图谱、时间滑块、搜索
```

## 摄取 vs. 检索

这个区分很重要：

| 你想要 | 使用 | 写入位置 |
|---|---|---|
| 把知识永久保存为页面 | `/wiki-history-ingest` | 写入 vault |
| 找到某件事发生在哪个会话 | `/session-brain` + `/session-search` | 仅写入 sidecar |

Session brain **绝不写入你的 vault**。所有东西都落在 `~/.claude/session-brain/`（用
`WIKI_SESSION_BRAIN_DIR` 覆盖）。

## 聚类是如何工作的

本地 TF-IDF，加上在 k 近邻图上的社区发现。没有 embedding，没有 API 调用，没有新依赖——这正是冷启动
构建只要约三秒的原因。

排序会对 90 天应用指数时间衰减并带下限，因此近期的工作会先浮现，而一个旧的精确匹配仍然会胜过新的弱
匹配。可以在构建时用 `--half-life` 调整半衰期，也可以按每次查询覆盖。

## 从 agent 使用

| 命令 | 作用 |
|---|---|
| `/session-brain` | 构建图谱，并为已发现的主题簇命名 |
| `/session-search <topic>` | 找到匹配的会话，并把它的 transcript 载入当前对话 |

通过 `/session-brain` 分配的簇名是持久的——它们能跨重建保留，并与生成的图谱分开存储。

## 调整构建

```bash
graph-wiki sessions-build --k 12 --min-sim 0.12 --mutual
```

| 参数 | 效果 |
|---|---|
| `--k N` | 每个会话的邻居数（默认 8）。越高 → 图越稠密、簇越大 |
| `--min-sim F` | 一条边的最低余弦相似度（默认 0.08）。越高 → 连接更少但更强 |
| `--mutual` | 只保留互为 kNN 的边——更紧凑、更小、更精确的簇 |
| `--half-life D` | 新鲜度半衰期（天，默认 90） |
| `--since DATE` | 只读取修改时间不早于某个 ISO 日期的会话 |
| `--skip a,b` | 跳过匹配这些子串的项目目录（或设置 `WIKI_SKIP_PROJECTS`） |
| `--full` | 忽略缓存，重新读取每个会话 |
| `--no-html` | 跳过写入 `graph.html` |
| `--bookmarks PATH` | 从另一个 `bookmarks.json` 读取书签（默认 `~/.bookmark-agent/bookmarks.json`） |
| `--claude-dir PATH` | 读取另一个 agent 的会话缓存 |

> 缓存目录名以 `-` 开头，argparse 会把它当成参数。请传裸名（`--skip game`），或使用
> `--skip=-w-game`。

重建默认是增量的——只有 mtime 变化的会话会被重新读取。

## 查询

```bash
graph-wiki sessions-query "auth bug" --project my-app --top 20
graph-wiki sessions-query "telemetry" --cluster 3 --since 2026-01-01 --json
```

| 参数 | 效果 |
|---|---|
| `--top N` | 返回的候选数（默认 10） |
| `--max-load N` | 建议载入的最大会话数（默认 3） |
| `--project NAME` | 限定到某个项目 |
| `--cluster ID` | 限定到某个主题簇 |
| `--since DATE` | 只返回结束时间不早于该 ISO 日期的会话 |
| `--min-score F` | 丢弃得分低于该值的候选（默认 0.05） |
| `--half-life D` | 覆盖构建时的新鲜度半衰期 |

## 交互式图谱

```bash
open ~/.claude/session-brain/graph.html
```

自包含的 HTML——没有 server，没有构建步骤。节点是会话，按簇着色；时间滑块按新鲜度过滤；搜索会就地
高亮匹配。

如果你只用 CLI，可以用 `--no-html` 跳过生成它。
