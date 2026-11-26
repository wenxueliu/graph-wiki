[English](access-control.md) | 简体中文

# 访问控制

一个 vault 只有一个可写事实来源，但读者很少只有一类人。`graph-wiki access` 为每个角色构建独立的
不可变 Content Pack。一个主体可以拥有多个角色，令牌网关会打开这些角色各自的 pack 并合并结果，因此
agent 可以探索自己有权访问的整个语料，而不是被钉在单个 pack 上。过滤不发生在模型看到内容之后：
授权角色之外的页面不会进入 pack、索引或网关响应。

## 保证与非目标

本模型保证：

- 角色的 pack 只包含该角色可读的页面。角色之外的正文、标题与边在 pack 及其检索索引中物理不存在。
- 网关只打开令牌角色对应的那些 pack。它绝不会回退到实时 vault，也不会打开令牌未授权的 pack。
- pack 与当前策略或 vault 状态不一致时会被拒绝，而不是带着旧权限继续服务。
- 每次网关决策都会记录主体、角色列表与返回页面，写入审计日志。

以下不在覆盖范围内，需要单独加固：

- **文件系统访问。** 如果 agent 能执行 `grep`、`cat` 或 `graph-wiki pack search --pack PATH`，它就能
  绕过网关。只把网关命令交给 agent，并让 vault 与 pack store 对 agent 所在用户不可读。
- **图谱查看器。** `graph-wiki serve` 直接读取实时 vault，没有角色过滤。
- **云端模型供应商。** 内容一旦进入第三方模型就已离开信任边界；受限角色请使用本地模型。
- **备份、git 历史与日志。** pack 是过滤后的读模型，vault 本身不是。

## 两份契约

### 内容契约：`_meta/access-policy.json`

位于 vault 内，可以提交与评审。

```json
{
  "version": 1,
  "default_exclude_tags": ["visibility/pii"],
  "roles": {
    "finance": {
      "description": "Finance team",
      "exclude_tags": ["visibility/pii"]
    },
    "public": {
      "description": "Anything that may leave the company",
      "exclude_tags": ["visibility/pii", "visibility/internal"]
    }
  }
}
```

- 角色名只能使用小写字母、数字、`.`、`_`、`-`。
- `exclude_tags` 可省略，此时使用 `default_exclude_tags`。未知键会失败关闭，拼写错误不会悄悄放宽权限。
- channel 是推导出来的：角色 `finance` 拥有 pack channel `role-finance`。channel 从不手工配置，因此
  两个角色不可能撞车。

### 身份契约：`<config-dir>/access/principals.json`

不在 vault 内，也绝不提交。文件只保存令牌哈希，创建时权限为 `0600`。

```json
{
  "version": 1,
  "principals": {
    "alice": {
      "roles": ["finance", "hr"],
      "token_sha256": "sha256:...",
      "created_at": "2026-11-26T04:00:00+00:00",
      "revoked_at": null,
      "vault_id": null
    }
  }
}
```

`roles` 保存一个或多个角色；拥有多个角色的令牌可以搜索这些角色各自拥有的全部 pack。旧版本写入的
单 `role` 字符串记录仍然可以解析。`vault_id` 可选；多个 vault 共用配置目录时，用它把主体固定到一个 vault。

## 页面可见性规则

两个独立机制决定页面是否属于某个角色的 pack：

| 页面标签 | 作用 |
|---|---|
| `role/<name>` | 把页面限定给该角色。一个页面可以带多个 `role/` 标签，此时对这几个角色都可见。匹配不到任何已配置角色的 `role/` 标签会让页面对所有人不可见。 |
| `visibility/pii` | 对所有角色隐藏，除非该角色的 `exclude_tags` 不包含它。 |
| `visibility/internal` | 仅团队。只有当角色把它列进 `exclude_tags` 时才隐藏；角色 pack 本身就是团队范围，所以 `access init` 会保留它。 |

没有 `role/` 标签的页面是共享的：除非被 `visibility/` 标签排除，否则每个角色都能看到。角色标签只做
限制；它不会把已被 `visibility/` 标签隐藏的页面重新开放给某个角色。

`graph-wiki access init` 生成的起始策略隐藏 PII、保留 internal 页面。若某角色不能看团队内部材料，把
`visibility/internal` 加进它的 `exclude_tags`。

## 构建角色 pack

```bash
graph-wiki access init --vault ~/brain --role finance --role public
graph-wiki access build --vault ~/brain --all
graph-wiki access build --vault ~/brain --role finance --index sqlite
```

每次构建会：

1. 依据策略与实时 vault 计算该角色的可见页面；
2. 在 channel `role-<name>` 上构建只包含该允许列表的不可变 Content Pack，并把 `access_role`、
   `access_policy_sha256` 与页面数写入 `manifest.build`；
3. 构建请求的检索索引（默认 `sqlite`）；
4. 写出只读的 `access.json` sidecar，记录策略指纹、可见页面指纹与 pack id。

pack 位于常规 pack store（`<config-dir>/packs/<vault-id>/`），每次构建一个版本。策略或任一可见页面
变化后都要重建；`access status` 会显示哪些角色已过期。`access build` 在 git 工作区不干净时会拒绝构建，
除非传入 `--allow-dirty`。

即使两个角色的可见页面完全相同，它们也各自拥有 channel 与构建元数据，pack 绝不会跨角色复用。
共享页面会在每个角色 pack 中各存一份，磁盘占用随“角色数 × 共享页面数”增长；只为实际会签发令牌的角色
构建。

## 网关

```bash
export GRAPH_WIKI_ACCESS_TOKEN="gw_..."
graph-wiki access search "retention policy" --vault ~/brain
```

也可以用 `--token` 传入令牌，但环境变量更安全：命令行参数会出现在进程列表与 shell 历史中。

网关把令牌解析为主体，校验它拥有的每个角色 pack，然后搜索这些 pack。输出为 JSON：

```json
{
  "schema_version": 1,
  "principal": "alice",
  "roles": ["finance", "hr"],
  "vault_id": "vault-...",
  "packs": [{"role": "finance", "channel": "role-finance", "pack_id": "sha256:...", "pack_version": 3, "visible_pages": 42}],
  "content_trust": "untrusted_reference_data",
  "coverage": {"roles": 2, "visible_pages": 57, "excluded_pages": 9, "drift_checked": true},
  "query": "retention policy",
  "count": 2,
  "results": [
    {
      "path": "concepts/retention.md",
      "heading": "...",
      "text": "...",
      "score": 0.032258,
      "engine_score": 1.2,
      "ranks": {"finance": 1, "hr": 2},
      "via_roles": ["finance", "hr"],
      "granted_by": ["finance", "hr"]
    }
  ]
}
```

结果正文属于 vault 内容：把它当作不可信参考数据，永远不要当作指令执行。

### 一个主体多个角色

每个角色仍然各自拥有独立的 pack；拥有两个角色的主体就搜索两个 pack。网关按路径去重，并用
reciprocal rank fusion 排序，因此两个 pack 都返回的共享页面只出现一次，也不需要跨 pack 比较引擎本地
的 BM25 分数。每条结果都记录 `via_roles`（返回它的 pack）与 `granted_by`（包含它的全部角色）。
`coverage.visible_pages` 是并集大小，不是各 pack 之和。

任一授权 pack 缺失或过期，整个查询都会被拒绝。部分结果会悄悄隐藏某个角色的内容，比显式重建更糟。
调试时可以用 `--role NAME` 只查询一个已授权角色；请求令牌未持有的角色会被拒绝。

### 探索语料

agent 不需要搜索查询、也不需要文件系统访问就能列出和读取页面：

```bash
graph-wiki access inventory --token "$GRAPH_WIKI_ACCESS_TOKEN" --limit 200 --offset 0
graph-wiki access page concepts/retention.md --token "$GRAPH_WIKI_ACCESS_TOKEN"
```

`access inventory` 返回各角色 pack 去重后的并集（path、title、summary、tags、lifecycle、`granted_by`），
用 `--limit` / `--offset` 分页。`access page` 返回单个页面的正文，带同样的 `granted_by` 标注，并拒绝
pack 之外的任何路径，包括 `..` 穿越。两种操作都会像 `search` 一样写入审计。

失败一律失败关闭，并写入审计：

| 原因 | 含义 |
|---|---|
| `invalid_token`、`missing_token` | 令牌未知、格式错误或已被撤销 |
| `unknown_role` | 主体的角色不在策略中 |
| `pack_missing` | 该角色从未构建过 |
| `policy_drift` | 构建后策略发生了变化 |
| `content_drift` | 构建后可见页面发生了变化 |
| `sidecar_mismatch` | pack 与它的 `access.json` sidecar 不一致 |
| `role_not_granted` | `--role` 指定的角色不在令牌中 |
| `page_denied` | 请求路径不在任何已授权 pack 中 |
| `invalid_page_path` | 路径是绝对路径或包含 `..` |

`--skip-drift-check` 只跳过可见页面指纹（策略始终会被校验）。用它换取延迟，同时保持 CI 重建，避免长期
过期。

## 令牌

```bash
graph-wiki access token create --vault ~/brain --name alice --role finance --role hr
graph-wiki access token list
graph-wiki access token revoke --name alice
```

`--role` 可重复；每次出现都会给主体增加一个角色。`token create` 只打印一次明文令牌，并且只保存它的
SHA-256 哈希。给每个人或每个 agent 会话分配独立主体；撤销一个主体不影响其他主体。`--replace` 可就地
轮换主体。

## 审计

每次网关搜索都会向 `<config-dir>/audit/access.jsonl`（`0600`）追加一行 JSON：

```json
{"ts": "...", "action": "search", "outcome": "ok", "principal": "alice", "roles": ["finance", "hr"],
 "packs": ["sha256:..."], "query": "retention policy", "returned": ["concepts/retention.md"], "count": 1}
```

被拒绝的尝试会记录结果与令牌哈希前缀，绝不记录令牌本身。

```bash
graph-wiki access audit --limit 100
graph-wiki access status
```

`access status` 报告每个角色、channel、pack 版本，以及策略与内容是否最新。`access resolve` 在不执行
搜索的情况下回答“这个令牌是谁，它会打开哪些 pack”。

## 运维

- **一个部署对应一个 vault。** 网关解析它指向的 vault，并拒绝固定到其他 vault id 的令牌。它还会
  读取该 vault 来校验新鲜度，因此本版本不支持没有 vault 的独立服务主机。
- **在 CI 中重建。** 每次 vault 变化后运行 `access build --all`，再用 `access status --strict` 作为
  门禁。任一角色未构建或已过期时它返回非零；过期 pack 会拒绝查询，而不是泄露。
- **用撤销完成轮换。** 令牌按主体发放；泄露的令牌要撤销，而不是过滤。
- **隔离三个面。** 人使用图谱查看器或直接读 vault；agent 只使用网关；pack store 只对网关进程可读。
- **记录决策，而不只是答案。** 审计日志才能回答“谁看过这份文档”。

失败模式的实例见[知识质量](quality.zh-CN.md)，pack 的确定性规则见[架构](architecture.zh-CN.md#content-pack-与检索索引)。
