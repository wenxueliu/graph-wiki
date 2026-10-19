[English](contributing.md) | 简体中文

# 贡献指南

项目还处在早期。skill 已经能用，但让这个大脑更聪明还有很大空间：更好的交叉引用、更锐利的去重、更大的
vault、新的摄取来源。如果你一直在琢磨这个问题，或者有某个可以做成 skill 的工作流，欢迎提 PR。

## 新增一个 skill

1. 在 `.skills/your-skill-name/` 创建一个文件夹
2. 添加带 YAML frontmatter（`name`、`description`）与 markdown 指令的 `SKILL.md`
3. 在项目中运行 `obsidian-wiki setup`，把它链接进所选的 agent 目录
4. 向你的 agent 说一句与 description 匹配的话来测试

`description` 是关键——它是 agent 在判断你的 skill 是否相关时唯一能看到的东西。请把它写成一串用户实际
会说的话，并且在容易与相邻 skill 混淆时，明确说明这个 skill **不** 用于什么。

完整指南见 [`.skills/skill-creator/SKILL.md`](../.skills/skill-creator/SKILL.md)，或者直接让你的 agent
运行 `/skill-creator`。

新增 skill 时，也要把它加到 [skills 参考](skills.zh-CN.md) 与 `AGENTS.md` 的路由表中。

### Workflow 支撑的 skill

顶层 `workflows/*.yaml` 是其同名 Agent Skill 的权威执行契约。修改 workflow 后，同步并检查
`.skills/<name>/SKILL.md`：

```bash
python tools/sync_workflow_skills.py
python tools/sync_workflow_skills.py --check
```

生成器会把 workflow 的 `do`、`input`、`output`、`check` 与流程控制字段确定性地渲染为 Agent Skill
markdown 指令；它绝不把原始 YAML 交给 agent 运行时解释。不要手工编辑生成的 `SKILL.md`；行为变更应
先落在 workflow。

## 新增一个 Knowledge Pack

`knowledge-packs/<name>/` 下的一个目录是一个完整的 Knowledge Pack，而不只是一个文件夹模板。它必须
包含：

```text
profile.json          # 语义目的、范围、知识与信任契约
layout.json           # pack 身份，以及对 profile/routing 契约的引用
routing.json          # 确定性的 page-type-to-path 规则
routing.md            # 语义放置指引
vault/                # 仅缺失时补齐的 schema、规则、术语与目录模板
```

保持边界清晰：

- 把目的、包含/排除范围、持久化知识类型、提取保留/省略规则、权威来源、检查、新鲜度触发条件与检索
  优先级放进 `profile.json`。
- 把内容根目录、系统区、占位符与路径模板放进 routing/Layout 文件。
- 把领域页面校验放进 vault schema。不要用目录名替代知识类型的定义。

Profile 的 `name` 必须与 pack/Layout 名称一致，每个 `knowledge_types` 条目都必须有已声明的路由，且
范围失配时必须选择 `ask`、`stage` 或 `reject`；Profile 绝不自动切换目标领域。当契约形态变化时，请补充
loader、marker、context-resolution 与针对性测试。

## 保持翻译同步

项目只以两种语言发布文档：英文（`.md`）与简体中文（`.zh-CN.md`）。`README.md` / `README_ZH.md` 是根
目录的一对；`docs/` 下每个页面都有英文 `<name>.md` 与简体中文 `<name>.zh-CN.md` 镜像。

每一对都是 **同一个文档面**。请保持标题、示例、链接、命令、数字与用户可见行为一致。不要加入其他语言
——繁体中文与其他所有 locale 都不在范围内。

每个英文页面以一行语言切换开头，其镜像则链回英文：

```markdown
English | [简体中文](<name>.zh-CN.md)          <!-- docs/<name>.md -->
[English](<name>.md) | 简体中文                 <!-- docs/<name>.zh-CN.md -->
```

`tests/test_docs_language_policy.py` 会强制校验镜像集合、切换行，以及不存在 `zh-TW`/其他 locale 文件。
README 漂移由 `readme-translation-drift` CI 任务报告，但不作为合并门禁：

```bash
python tools/check_readme_sync.py
```

该工具会为每个翻译列出那些修改了 `README.md` 却没有对应翻译后续更新的提交，以及待完成的英文 diff。
请把这些内容翻译并回填进各翻译文件。翻译质量由审查者评估。

## 仓库约定

- `.skills/` 是事实来源。`.claude/skills/`、`.agents/skills/` 等项目目标是 `obsidian-wiki setup` 创建
  的链接；`~/.codex/skills/` 等旧版全局目标可能由 `python3 setup.py` 创建。绝不要编辑链接副本。
- `CLAUDE.md`、`GEMINI.md` 与 `.hermes.md` 是指向 `AGENTS.md` 的符号链接。请编辑 `AGENTS.md`。
- 新的配置变量属于三个地方：`.env.example`、[`docs/configuration.md`](configuration.zh-CN.md)，以及读取
  它的那个 skill。
- 新的 CLI 子命令属于 [`docs/cli.md`](cli.zh-CN.md)。
- 新的面向用户的 skill 属于 [`docs/skills.md`](skills.zh-CN.md) 与 `AGENTS.md` 的路由表。

## 测试

```bash
pytest
```

测试位于 `tests/`。可以确定性断言的 skill 行为（配置解析、manifest 处理、图谱数学、会话索引）在那里
有覆盖；由 LLM 驱动的部分没有。
