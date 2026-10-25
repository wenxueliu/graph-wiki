<h1 align="center">graph-wiki</h1>

<p align="center"><b>一个由 AI agent 陪你一起养大的数字大脑。</b></p>

<p align="center">
  它会记住你弄懂的事，把新知识连到你已经知道的内容，<br>
  并在你提问时回答。
</p>

<p align="center">
  <a href="https://pypi.org/project/graph-wiki-skills/"><img src="https://img.shields.io/pypi/v/graph-wiki-skills?color=blue" alt="PyPI" /></a>
  <a href="https://deepwiki.com/wenxueliu/graph-wiki"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
  <a href="https://github.com/wenxueliu/graph-wiki/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
</p>

<p align="center">
  <img width="768" alt="graph-wiki" src="https://github.com/user-attachments/assets/b44cf63b-3197-4fb1-8e18-dbc9a39f27a7" />
</p>

<p align="center">
  <a href="https://github.com/wenxueliu/graph-wiki/blob/main/README.md">English</a> | 简体中文
</p>

---

你在某个星期二解掉一个难题。三个月后，在另一个 repo 里，你又从头解了一次——因为答案躺在一份你永远找不到的对话记录里。

这个项目解决那个问题。指定一个文件夹，告诉你的 agent 要记住什么，它就会把你学到的东西编译成彼此连接、而且属于你自己的 markdown。这个模式来自 Andrej Karpathy 的 [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)：把知识编译一次并持续维护，而不是每次都问 LLM 同样的问题，或每次都重新跑 RAG。

**你的第二大脑。你的 AI agent 让它持续成长。**

这里每个 skill 都是一个 markdown 文件，任何 agent 都能读取并执行，包括 Claude Code、Cursor、Codex、Windsurf、Gemini CLI，以及[更多](https://github.com/wenxueliu/graph-wiki/blob/main/docs/agents.zh-CN.md)。确定性的本地工具负责哈希与受限文本区段；不需要托管 runtime、API key，也不绑任何厂商。

## 60 秒上手

```bash
pip install graph-wiki-skills
cd /path/to/your/project
graph-wiki setup
```

Setup 只会把 skills 安装到当前项目。接着在你的 agent 里打开该项目，说 **"set up my wiki"**。

不想碰终端？把下面这行交给你的 agent，它会全部处理好：

```text
https://github.com/wenxueliu/graph-wiki — set up my wiki
```

其他安装方式（`git clone`、Skills CLI、多个 vault）请见 **[安装说明](https://github.com/wenxueliu/graph-wiki/blob/main/docs/installation.zh-CN.md)**

## 你实际会做的事

**喂养它。** 本地 Markdown、纯文本与 reStructuredText 文档会通过可续传、受上下文限制的
管线导入。Agent 历史与网络研究则使用各自的专用 skill。

```text
/wiki-folder-ingest ~/research
/wiki-update                        # 蒸馏你目前所在的这个 repo
/wiki-capture                       # 把这段对话存下来
/wiki-history-ingest claude         # 挖出你问过 Claude 的所有东西
```

**问它。** 回答会附上 `[[wikilink]]` 引用，而不是凭感觉。

```text
/wiki-query what do I know about rate limiting?
/wiki-narrate MCP security          # 针对一个主题生成有引用的简报
/wiki-digest week                   # 我这周学到了什么？
```

**找出那个你叫不出名字的 session。**

```bash
graph-wiki sessions-build
graph-wiki sessions-query "the auth bug with the weird retry loop"
```

**维持它的品质。** vault 自己会变乱，这些 skill 负责整理。

```text
/wiki-lint            # 坏掉的链接、孤儿页面、互相矛盾的内容
/wiki-dedup           # "RSC" 和 "React Server Components" 现在是同一页了
/cross-linker         # 把新页面编织进知识图谱
/wiki-status          # 已导入什么、还有什么待处理、枢纽页面在哪
```

全部 50 个 skill 请见 **[Skills Reference](https://github.com/wenxueliu/graph-wiki/blob/main/docs/skills.zh-CN.md)**

## 看见它

在 Obsidian 打开 vault，然后开启 graph view（Cmd/Ctrl+P → "Open graph view"）。说 **"color my graph"**，它就会依照 tag、category 或 visibility 为节点上色。

<p align="center">
  <img width="900" alt="graph-wiki graph view" src="https://github.com/user-attachments/assets/f2980840-4b5b-438a-8264-5ad1de42f483" />
</p>

你也可以把整个图谱导出成 `graph.json`、GraphML（Gephi/yEd）、Neo4j Cypher，或一个自带所有资源的交互式 `graph.html`。

## 为什么不是一个笔记文件夹就好

- **它会编译，而不是堆积。** 新知识会合并进既有页面，矛盾会被标记出来，内容不会重复。
- **它只读有变动的部分。** manifest 追踪每个导入过的来源，所以第二次执行只处理差异，而不是重跑整个库。
- **你分得出哪些是知识、哪些是猜测。** 每个陈述都会标记为 `extracted`、`^[inferred]` 或 `^[ambiguous]`，lint 会标出开始偏向臆测的页面。
- **查询成本不随规模爆炸。** 先读标题、tag 和 summary，需要时才打开页面内容。20 页或 2000 页，成本差不多。
- **它是你的。** 就是文件夹里的纯 markdown。推到私人 repo、用 Obsidian 打开、用 grep 搜、直接删掉都行。没有服务、没有锁定，什么都不会离开你的机器。
- **在你原本工作的地方就能用。** 一个 bundled `.skills/` 目录，链接到项目内每个选定的 agent。

更多细节请见 **[Architecture](https://github.com/wenxueliu/graph-wiki/blob/main/docs/architecture.zh-CN.md)**

## 文档

以下文档同时提供英文与简体中文版本；下方链接指向简体中文版。

| | |
|---|---|
| **[Installation](https://github.com/wenxueliu/graph-wiki/blob/main/docs/installation.zh-CN.md)** | pip、clone、由 agent 设置、多个 vault |
| **[Skills Reference](https://github.com/wenxueliu/graph-wiki/blob/main/docs/skills.zh-CN.md)** | 全部 50 个 skill 与其 slash command |
| **[Agent Compatibility](https://github.com/wenxueliu/graph-wiki/blob/main/docs/agents.zh-CN.md)** | 完整兼容性表格与各 agent 手动设置 |
| **[CLI Reference](https://github.com/wenxueliu/graph-wiki/blob/main/docs/cli.zh-CN.md)** | 每一个 `graph-wiki` 子命令 |
| **[Configuration](https://github.com/wenxueliu/graph-wiki/blob/main/docs/configuration.zh-CN.md)** | 设置变量、QMD 语义搜索、`_raw/` 暂存区、GitHub 同步 |
| **[Architecture](https://github.com/wenxueliu/graph-wiki/blob/main/docs/architecture.zh-CN.md)** | 四个导入阶段、vault 结构、我们在 Karpathy 模式上加了什么 |
| **[Session Brain](https://github.com/wenxueliu/graph-wiki/blob/main/docs/session-brain.zh-CN.md)** | 建立在 agent session 历史之上的主题图谱 |
| **[Contributing](https://github.com/wenxueliu/graph-wiki/blob/main/docs/contributing.zh-CN.md)** | 新增 skill、维持中英双语文档同步 |

## 参与贡献

这个项目还很早期。skills 是能用的，但还有很多空间让这个大脑变得更聪明：更好的交叉引用、更精准的去重、支撑更大的 vault、更多导入来源。如果你有一个工作流程适合做成 skill，[欢迎提交 PR](https://github.com/wenxueliu/graph-wiki/blob/main/docs/contributing.zh-CN.md)。

## 授权

[MIT](https://github.com/wenxueliu/graph-wiki/blob/main/LICENSE)
