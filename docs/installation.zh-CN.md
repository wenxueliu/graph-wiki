[English](installation.md) | 简体中文

# 安装

四条路径。选一条——它们最终都到达同一个地方：配置文件（由 setup 创建的项目为 `<project>/.graph-wiki/config`；未设置时为 `~/.graph-wiki/config`）里的 vault
路径，以及你的 agent 能发现的 skill。

| 路径 | 适合谁 | 写入配置 | Agent skill 目标 |
|---|---|---|---|
| [pip](#通过-pip-安装推荐) | 大多数人 | ✅ | 由用户选择，仅命令所在目录 |
| [让你的 agent 来做](#让你的-agent-来设置) | 不需要终端 | ✅ | 当前 agent |
| [git clone + `python3 setup.py`](#通过-git-clone-安装) | 贡献者、喜欢折腾的人 | ✅ | 项目本地全 agent 安装器 |
| [Skills CLI](#通过-skills-cli-安装已废弃) | 已废弃——部分安装 | ❌ | 仅当前 agent |

## 通过 pip 安装（推荐）

```bash
pip install graph-wiki-skills
graph-wiki setup --vault /path/to/your/digital/brain
```

`graph-wiki setup` 会把配置写入 `<project>/.graph-wiki/config`（随附的 `.env.example` 设置了
`GRAPH_WIKI_CONFIG_DIR=.graph-wiki`；留空则使用 `~/.graph-wiki`），并询问要安装哪些 agent skill 目标。
它没有隐含的「安装全部 agent」行为，也从不把 skill 装到全局。skill 与 bootstrap 文件只会写在命令运行
所在的目录下（或显式 `--project DIR` 覆盖的目录）。skill 以符号链接指向已安装的包，因此
`pip install -U graph-wiki-skills` 之后再次运行 setup 即可升级所选目标。

对于脚本与其他非交互环境，请显式选择目标：

```bash
graph-wiki setup --vault /path/to/brain --knowledge-pack default --agent claude --agent codex
graph-wiki setup --vault /path/to/brain --knowledge-pack software-knowledge --agent claude,codex,pi
graph-wiki setup --vault /path/to/brain --knowledge-pack default --agent all
```

运行 `graph-wiki setup --list-agents` 可查看稳定的项目本地目标名。非交互式 setup 必须显式选择；
只有在你确实想「配置 vault 但不安装 agent skill」时才用 `--agent none`。

如果在终端中省略 `--knowledge-pack`，setup 会列出可用的 Knowledge Pack 并要求你选择一个。Agent 选择
接受多个值；Knowledge Pack 选择始终是单选。非交互式 setup 必须显式传 `--knowledge-pack NAME`。

然后在 agent 中打开该目录，说 **「set up my wiki」**。

常用参数：

```bash
graph-wiki setup --project /work/app  # 覆盖命令所在目录这一目标
graph-wiki setup --copy        # 复制 skill 文件，而不是创建符号链接
```

使用 `software-knowledge` Pack 做自包含的项目安装：

```bash
graph-wiki setup --knowledge-pack software-knowledge --copy --agent cursor
```

这会选择 `software-knowledge` Knowledge Pack，初始化已配置的 vault，安装所选 agent 的项目本地 skill
与 bootstrap 文件，并在命令所在目录下从打包模板补上一个缺失的 `.env`。已废弃的 `--project-only` 参数
作为空操作保留以兼容旧用法，因为 CLI setup 已经没有全局 skill 安装阶段。`--copy` 会写入独立的 skill
文件而不是符号链接，在项目必须自包含时很有用。

项目 `.env` 只在不存在时创建；setup 绝不覆盖已有的项目配置。传入 `--vault` 时，其解析后的绝对路径会
写入新 `.env` 的 `OBSIDIAN_VAULT_PATH`。Setup 还会补齐 `.env.example` 声明的稳定 context 绑定：
Knowledge Pack、owner/Writing Profile 路径、vault 元数据与 taxonomy 路径，以及持久化的已编译 context
快照路径。已有 `.env` 文件会被保留，只有缺失或空白的稳定绑定键会被填补；非空的自定义值、未知字段与
注释都会保留。更改这些绑定后请运行 setup/repair。

`OBSIDIAN_VAULT_PATH` 只是你希望数字大脑存放的任意目录——一个新建的空文件夹或一个已有的 Obsidian
vault 都行。在交互式终端中省略 `--vault` 即可进入输入；显示的默认值是当前目录，按 Enter 接受。在
非交互式运行中，请显式传 `--vault`，或使用配置文件（由 setup 创建的项目默认 `<project>/.graph-wiki/config`；否则 `~/.graph-wiki/config`）中的既有值。

Agent 选择也会过滤生成的项目规则与入口文件。例如只选 Claude，会创建共享的 `AGENTS.md`、`CLAUDE.md`
与 `.claude/skills/`，而不会生成其他 agent 的文件。选择多个 agent 会生成它们文件的并集。

运行 `graph-wiki info` 查看解析后的路径，运行 `graph-wiki doctor` 对结果做健康检查。该包提供的
其他所有命令见 [CLI 参考](cli.zh-CN.md)。

## 让你的 agent 来设置

最快的路径——不需要任何命令。把这个 repo 交给你的 agent，然后说：

```text
https://github.com/wenxueliu/graph-wiki — set up my wiki
```

Agent 会从 repo 读取 [`.skills/wiki-setup/SKILL.md`](../.skills/wiki-setup/SKILL.md)，询问你希望
vault 放在哪里，并初始化完整结构：目录、index、log、Obsidian 配置，以及一个可选的自动采集 hook。这个
skill **就是** 安装指南。

它在任何能读文件的 agent 中都能用（Claude Code、Cursor、Windsurf、Codex、Gemini CLI、Kiro 等）。
设置完成后，所有 wiki skill 立即可用。

## 通过 git clone 安装

```bash
git clone https://github.com/wenxueliu/graph-wiki.git
cd graph-wiki
python3 setup.py
```

`python3 setup.py` 会询问你的 vault 路径，然后委托给已安装的 CLI 执行
`graph-wiki setup --agent all`。配置默认写入 `<project>/.graph-wiki/config`（随附的
`.env.example` 设置了 `GRAPH_WIKI_CONFIG_DIR=.graph-wiki`），skill 只安装到当前项目（Windows
用复制模式，Unix 用符号链接），不会写入任何全局 agent 目录。

在 agent 中打开该项目，说 **「set up my wiki」**。

若要仅本地配置，把 `.env.example` 复制为 `.env` 并设置 `OBSIDIAN_VAULT_PATH`。工作目录（或其到
`$HOME` 为止的任意父目录）中的 `.env` 优先于配置文件。随附模板已设置
`GRAPH_WIKI_CONFIG_DIR=.graph-wiki`，因此复制出的 `.env` 会把整个配置留在项目内；将该值留空则使用
`~/.graph-wiki`。此后所有与 vault 相关的命令
（`query`、`context-pack`、`lint`、`trust-*`、`validate`、`verify`、`doctor`、`sync`）都读取项目的
`.env`，`@name` profile 也从 `<project>/.graph-wiki/config.<name>` 解析。见
[Configuration](configuration.zh-CN.md#把配置留在项目内)。

### What `python3 setup.py` wires up

`python3 setup.py` 是已安装 CLI 的薄封装：它在当前 checkout 中运行
`graph-wiki setup --agent all`，因此源码安装与 pip/uv 安装共享同一套实现。它会写入：

1. **配置**，默认位于 `<project>/.graph-wiki/config`（随附的 `.env.example` 设置了
   `GRAPH_WIKI_CONFIG_DIR=.graph-wiki`；留空则为 `~/.graph-wiki`），包含你的
   vault 路径与 repo 位置。skill 正是借此知道该从哪里读写。
2. **项目本地 skill 镜像**——`.claude/skills/`、`.cursor/skills/`、`.windsurf/skills/`、`.pi/skills/`、`.cac/skills/`、`.kiro/skills/` 为符号链接（传 `--copy` 时为副本），共享的 `.agents/skills/` 则始终是副本
3. **Always-on 规则文件**——`CLAUDE.md`、`GEMINI.md`、`AGENTS.md`、`.hermes.md`、`.cursor/rules/…`、`.windsurf/rules/…`、`.kiro/steering/…`、`.agent/rules/…`、`.agent/workflows/…`、`.github/copilot-instructions.md`
4. **GitHub 同步**（可选）——见 [Configuration → 把 vault 同步到 GitHub](configuration.zh-CN.md#把-vault-同步到-github)

不会把任何 skill 写入 `~/.claude/skills`、`~/.codex/skills` 或其他用户主目录下的目录。
`graph-wiki setup` 只安装你选择的 agent；`setup.py` 传入的 `--agent all` 表示「当前项目中的
所有 agent」，而不是「全局所有 agent」。

## 通过 Skills CLI 安装（已废弃）

```bash
npx skills add wenxueliu/graph-wiki
```

它只把 markdown skill 装进当前 agent。它 **不会** 写入配置文件（`.graph-wiki/config` 或 `~/.graph-wiki/config`）、配置 GitHub 同步，
或铺设 `graph-wiki setup` 所完成的项目 bootstrap。`python3 setup.py` 源码安装器会委托给
`graph-wiki setup --agent all`，同样只作用于当前项目。

只有当你确实想要一个部分、仅限当前 agent 的安装，并且愿意自己管理配置时，才使用这条路径。要完整安装，
请改用 pip 或 git clone。

完整 skill 列表见 [skills.sh/wenxueliu/graph-wiki](https://skills.sh/wenxueliu/graph-wiki)。

## 在 Obsidian 中打开

在 Obsidian 中打开你的 vault 目录（File → Open Vault）。wiki 页面、wikilink 与 graph view 都能原生
工作。vault 没有任何专有之处——它就是带 YAML frontmatter 的 markdown 文件。

## 多个 vault

在配置文件（由 setup 创建的项目为 `<project>/.graph-wiki/config`；否则 `~/.graph-wiki/config`）中保持一个默认生效的 vault；需要命名配置时，把它复制为
`<config-dir>/config.work` 并修改其中的 `OBSIDIAN_VAULT_PATH`。

Profile 也可以放在项目内：由随附模板创建的 `.env` 已设置 `GRAPH_WIKI_CONFIG_DIR=.graph-wiki`，把
`config`、`config.<name>` 与 `WRITING.md` 留在该目录——不会读写 `~/.graph-wiki`。当一个仓库拥有一个 vault、
且多个仓库必须彼此独立时，这是推荐布局。`@name` 与普通默认值都在该目录内解析。

每个 profile 指向一个独立的 vault 目录，Obsidian 会把它们视为彼此独立的 vault：一次打开一个（或每个
窗口一个）。Obsidian 没有跨 vault 链接，没有合并后的图谱，也没有共享索引，因此 `@work` 下的内容不会
链接到 `@personal`，也无法从 `@personal` 检索到；一次 `wiki-query` 调用只读取一个 vault。除非知识确实
服务于不同的目的，否则请保持单一 vault。

在任意目录下，都可以用 `@name` 把单个请求路由到一个命名 vault：

```text
@work update wiki
@research save this
wiki-query @personal what do I know about MCP security
```

`@name` 覆盖 **只对该请求生效**，绝不改变你的默认 vault。要改变默认值，重新运行
`graph-wiki setup --vault <path>`，或把想用的 profile 覆盖到当前生效的 `config` 文件。

在 `graph-wiki setup` 或 `python3 setup.py` 之后，所有受支持的 agent 都能使用这个语法，因为共享的
skill 与 always-on bootstrap 文件都指回同一套 Config Resolution Protocol。Claude Code、Cursor、
Windsurf、Codex、Gemini、Kiro、Hermes、OpenClaw、Copilot CLI、Pi 以及通用的 `AGENTS.md` agent 都会
从同一份指令中读取它。

该路由 token 对写入类 skill（`@work update wiki`、`@research save this`）与读取类 skill
（`wiki-query @personal what do I know about X`）都有效。

## 验证安装

```bash
graph-wiki doctor
```

`doctor` 能发现安装损坏、安装过期与 vault 状态畸形。加 `--json` 可获得机器可读输出。

## 下一步

- [Skills 参考](skills.zh-CN.md) —— 你实际能要求什么
- [Configuration](configuration.zh-CN.md) —— 每个配置变量、QMD、GitHub 同步
- [Agent 兼容性](agents.zh-CN.md) —— 每个 agent 的细节与手动设置
