[English](quality.md) | 简体中文

# 知识质量控制

Wiki 可以增长得很快，同时变得不可信。质量控制的目的是让 vault 在增长过程中保持可审计：每条
持久陈述都能追到来源，每个页面都遵守当前契约，未解决的分歧保持可见，人能说清哪些置信度确实
被复核过。

`graph-wiki quality` 把这些关注点收敛为一份确定性的、可供门禁使用的报告。它是现有检查之上的
聚合层，不替代它们：

- `graph-wiki lint` 负责结构、schema 与关系问题。
- `graph-wiki trust-check` 负责置信度与复核台账的完整性。
- `graph-wiki verify` 负责 manifest 到页面的覆盖。
- `graph-wiki pack eval` 负责检索质量。
- `graph-wiki quality` 把上述结果与来源、provenance 覆盖合并成一个状态。

## 质量模型

| 维度 | 回答的问题 | 确定性信号 |
|---|---|---|
| 结构 | 页面集合是否合规且连通？ | 断链、缺失 frontmatter、缺失 summary、超大页面 |
| 可溯源性 | 陈述能否追到证据？ | 无 sources 的页面、无 provenance 的页面、非法 provenance、provenance 漂移 |
| 一致性 | 图谱是否存在明显重复和死胡同？ | 重复标题组、孤儿页、类型化关系问题 |
| 覆盖 | 每个登记的来源是否真的产出了页面？ | manifest 来源数、无页面来源、幽灵页面 |
| 时效 | lifecycle 是否仍然诚实？ | lifecycle 分布、缺失 lifecycle、材料指纹变化后的过期复核 |
| 可信 | 置信度是否经过人工复核？ | 台账是否存在、缺失 trust 字段、台账错误、分数不一致、过期与未复核页面 |
| 检索 | 知识能否被找到并使用？ | 在接入 `pack eval` 结果前报告为 `not_measured` |

每个维度返回 `pass`、`warn`、`fail` 或 `not_measured`。任一维度 `fail` 则总体 `fail`；否则
任一维度 `warn` 则总体 `warn`；否则 `pass`。`not_measured` 不会被悄悄当成通过：它会单独显示，
并附带说明应该运行什么命令。

## 四道闸门，而不是单一分数

质量在四个边界上执行。这个不对称是刻意的：采集应当宽松，发布应当严格。

| 闸门 | 何时运行 | 命令 | 失败行为 |
|---|---|---|---|
| G0 入口 | 来源进入 vault | Knowledge Pack scope 检查、`text-document-*` / `text-ingest-*` | 拒收或暂存；绝不写入半成品知识页 |
| G1 写入 | 页面创建或合并 | `page-check`、`validate`、page contract、canonical 合并检查 | 阻止写入并重试 |
| G2 发布 | vault 状态发布为 Content Pack | `lint`、`quality`、`trust-check`、`pack verify`、`pack eval` | 不发布 |
| G3 运行 | 查询与周期维护 | lifecycle 感知排序、`daily-update`、`wiki-lint` 语义审计 | 隐藏退役页、降权未定稿页、进入修复队列 |

`quality` 是 G2 的聚合器。它不修改 vault；它读取同一批文件，并返回适合 CI 使用的退出码。

## 运行检查

```bash
graph-wiki quality                     # 使用已配置的 vault，输出人类可读摘要
graph-wiki quality /path/to/vault      # 显式指定 vault
graph-wiki quality @research --json    # 命名配置，输出机器可读报告
graph-wiki quality --pretty --json
graph-wiki quality --strict            # warning 也让退出码非零
graph-wiki quality --require-trust-ledger   # 发布门禁：没有台账即失败
graph-wiki quality --strict-trust      # schema 缺口与过期复核按失败处理
graph-wiki quality --allow-lifecycle active \
  --schema-source /path/to/vault/AGENTS.md
```

退出码：`pass` 为 `0`（`warn` 在未加 `--strict` 时也是 `0`）；`fail` 或 `--strict` 下的
`warn` 为 `1`。命令解析 vault 与 schema 的方式与 `lint` 完全一致。

### 报告结构

```json
{
  "status": "warn",
  "generated_at": "2026-11-24T12:30:33+00:00",
  "vault": "/abs/path/to/vault",
  "schema": {"source": "framework-defaults", "allowed_lifecycles": ["..."], "...": "..."},
  "gate": {
    "strict_trust": false,
    "require_trust_ledger": false,
    "failed_dimensions": [],
    "warned_dimensions": ["traceability"]
  },
  "stats": {"pages": 42, "total_tokens": 31840, "manifest_sources": 7, "...": "..."},
  "dimensions": {
    "structure": {"status": "pass", "signals": {"broken_links": 0}, "notes": []},
    "traceability": {"status": "warn", "signals": {"missing_provenance": 3}, "notes": ["..."]},
    "trust": {"status": "not_measured", "signals": {"ledger_configured": 0}, "notes": ["..."]}
  },
  "metrics": {"lifecycle": {"draft": 4, "reviewed": 38}, "provenance": {"...": "..."}},
  "findings": {"broken_links": [], "traceability": {"missing_sources": []}, "coverage": {}}
}
```

`findings` 保留明细列表，CI 或看板可以渲染具体路径而不只是计数。`metrics` 携带适合看趋势的
数字：lifecycle 计数、provenance 均值、标记数量、重复标题组、超大页面与索引缓存一致性。

## 写入前门禁

`quality` 在事后度量 vault；`page-check` 则从一开始就阻止可避免的缺陷进入：agent 先把拟定页面写到
临时文件，通过检查后再写入 vault。

```bash
graph-wiki page-check --path concepts/rate-limiting.md --content /tmp/page.md --json
graph-wiki page-check @research --path concepts/rate-limiting.md --from-stdin --json
graph-wiki page-check --path concepts/rate-limiting.md --content /tmp/page.md --mode create
```

门禁合并三类检查：

1. **契约。** 与 `validate` 相同的必填 frontmatter，包括 `provenance` 块与不超过 200 字符的
   summary。
2. **路径。** 目标必须是 content root 内的安全 vault 相对 `.md`，不能是保留 special file 或系统区域。
3. **Canonical 身份。** 规范化标题与别名重复是警告；slug 冲突与相似标题/摘要是合并候选软信号。

`fail` 会阻止写入（`invalid_page`、`invalid_target`、create 时的 `target_exists`、update 时的
`target_missing`）。`warn` 要求做出决定：合并到报告的页面、改为更新目标页，或记录为什么独立页面
确实必要。`--strict` 会把重复警告变成非零退出，供自动化使用。

轻量 `wiki-ingest` 路径与可恢复 packet 归并中的 direct 写入会在替换 live 页面前调用该门禁。
staged artifact 由人工在提升前复核；把同一门禁接入 stage promotion 是下一个集成点。

## 严重级别策略

| 维度 | 失败条件 | 警告条件 |
|---|---|---|
| 结构 | 断链或缺少核心 frontmatter | 缺少 summary、页面超过 token 上限 |
| 可溯源性 | — | 缺少 sources、provenance 块缺失或非法、provenance 漂移 |
| 一致性 | — | 重复标题组、孤儿页、关系问题 |
| 覆盖 | manifest 条目没有页面，或页面在磁盘上不存在 | — |
| 时效 | — | 缺少 lifecycle、复核早于页面的材料指纹 |
| 可信 | trust 元数据非法、台账损坏、分数不一致 | 缺少 trust 字段、复核过期或未复核 |
| 检索 | — | —（在接入 pack 评估前为 `not_measured`） |

阈值与 `wiki-lint` workflow 的语义审计保持一致：ambiguous 超过 `15%`、无 sources 页面
inferred 超过 `40%`、lifecycle 不在解析后的 allowlist 内，都会成为 finding。加上
`--strict-trust` 后，缺失 trust 字段与过期复核也会进入失败列。

## 仍需人负责的部分

确定性检查能证明页面引用了来源，但不能证明来源支持该陈述。这个判断留给人，trust ledger 是
它的记录：

```bash
graph-wiki trust-record --all --reviewed-at 2026-11-24T10:00:00+00:00 --approved
graph-wiki trust-check --strict
```

`quality` 只报告台账状态，从不写入台账，也从不根据 URL 自动重算置信度。矛盾识别、provenance
分类、synthesis gap 等 agent 驱动的语义工作仍属于 `wiki-lint` skill。

## CI 示例

```yaml
- name: Install
  run: pip install graph-wiki-skills
- name: Knowledge quality gate
  run: graph-wiki quality "$VAULT" --strict --require-trust-ledger --json
```

在摄取之后、发布 Content Pack 之前运行 `quality`。对于只发布 skill 的仓库，也可以用同一个
命令对 fixture vault 做门禁。

## 当前范围

本次已交付：

- 确定性的 `quality` 报告与 CLI；
- 来源、provenance、lifecycle 的聚合；
- trust ledger 与 manifest 覆盖门禁；
- `--strict`、`--strict-trust`、`--require-trust-ledger` 三种门禁模式；
- 面向契约与 canonical 身份的 `page-check` 写入前门禁。

后续计划：

- 引用 locator 解析（来源路径加行号或锚点）；
- 将同一写入前门禁接入 staged promotion；
- 与 `wiki-lint` workflow 共享语义重复与矛盾信号；
- 在检索指标之外增加答案落地（answer grounding）评估；
- 按 vault 覆盖阈值，并建立趋势基线。

`quality` 是闸门，不是评分。它用于拦住已知的坏状态、暴露缺失的证据，而不是宣布某个页面正确。
