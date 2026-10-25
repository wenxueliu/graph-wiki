---
name: wechat-article-fetcher
description: "微信公众号文章抓取与归档. Use when the user wants to fetch, extract, export, or archive a WeChat Official Account article (mp.weixin.qq.com) into local Markdown, JSON, and HTML through the user's real browser via kimi-webbridge. Handles anti-bot verification hand-off, deleted or blocked pages, lazy-loaded images, and writes results to _raw/. [trigger: 微信文章, 公众号文章, 抓取微信, 导出公众号, 文章归档, wechat article, mp.weixin.qq.com, article to markdown]"
metadata:
  version: "1.0.0"
  external_dependencies:
    - name: kimi-webbridge
      version: ">=2.0"
      type: SKILL
      required: true
      purpose: drive the user's logged-in browser to render mp.weixin.qq.com articles and read the article DOM
---

# 微信公众号文章抓取 (wechat-article-fetcher)

## Overview

任意 `mp.weixin.qq.com/s/...` 文章 → 本地可检索的 Markdown、JSON、HTML。

微信对普通 HTTP 客户端返回「环境异常」验证页，所以本技能走 **用户的真实浏览器**：
`kimi-webbridge` 打开文章标签页 → 读取渲染后的 `#js_content` DOM →
转换为 Markdown 并归档到 `_raw/`。

**核心边界：**

- 不破解验证码，不使用第三方打码服务。桌面 UA 被挑战时脚本按微信移动端访问方式自动重试一次；仍被挑战则把浏览器交给用户人工验证，然后重跑。
- 不关闭用户浏览器中的标签页或会话。标签页由用户决定何时清理。
- 不猜测文章内容。只归档当前页面真实渲染出的正文。

**输入：** 一个 `mp.weixin.qq.com` 文章链接（可选输出目录、会话名、超时）。
**输出：** `_raw/<stem>.md`、`_raw/<stem>.json`、`_raw/<stem>.html`。

## When to Use

使用本技能当用户要求：

- 抓取 / 导出 / 保存 / 归档一篇微信公众号文章
- 把公众号文章转成 Markdown 供后续分析、知识库入库或引用
- 批量抓取公众号文章中的某一篇（逐篇调用本技能）
- 用户给出 `mp.weixin.qq.com/s/...` 链接并希望拿到正文

不要使用本技能当：

- 链接不是公众号文章（新闻站、知乎、博客等）→ 用 `sw-browser-tester` 或通用浏览器操作
- 只需要网页摘要、不需要完整正文
- 用户要求自动破解验证码或绕过反爬（拒绝，改为人工验证）

## Workflow

### 1. 运行抓取脚本

从技能目录执行：

```bash
python scripts/fetch_wechat_article.py <article-url> --output-dir _raw
```

常用参数：

| 参数 | 说明 |
|---|---|
| `-o, --output-dir` | 输出目录，默认 `_raw`（相对当前工作目录） |
| `--session` | kimi-webbridge 会话名，默认 `wechat-article-fetch` |
| `--daemon-url` | daemon 地址，默认自动探测或读 `KIMI_WEBBRIDGE_URL` |
| `--timeout` | 等待正文出现的最长秒数，默认 30 |
| `--no-html` | 不写独立 HTML 文件 |
| `--no-mobile-fallback` | 遇到环境验证页时不自动切换移动端微信 UA |
| `--json` | 机器可读输出，便于自动化消费 |

脚本会自动定位地址为 `127.0.0.1:10086` 的 daemon（或 `status` / `start` 报告的实际端口），
daemon 未运行时执行一次幂等的 `start`。

### 2. 处理退出码

| 退出码 | 含义 | 动作 |
|---:|---|---|
| `0` | 成功归档 | 汇报文件路径与字数 |
| `2` | URL 不受支持 | 请用户确认链接是 `mp.weixin.qq.com/s/...` |
| `3` | 需要人工完成微信验证 | 见下方「验证页处理」 |
| `4` | 文章不可访问（删除/屏蔽/迁移/客户端限制） | 如实汇报，不要伪造内容 |
| `5` | 等待正文超时 | 检查标签页是否仍在加载；可加大 `--timeout` 后重试 |
| `6` | daemon 或浏览器扩展不可用 | 按脚本提示启动 daemon / 连接扩展 |
| `7` | 写文件失败 | 检查输出目录权限 |

### 3. 验证页处理（退出码 3）

微信对桌面浏览器 / 自动化 UA 返回「环境异常，完成验证后即可继续访问」，但对手机微信客户端正常渲染文章。脚本按以下顺序处理：

1. **自动回退：** 检测到验证页后，通过 CDP 把当前标签页切换为移动端微信 UA，并重新加载文章。加载成功则继续归档，结束后恢复标签页 UA。
2. **人工验证：** 回退后仍是验证页时，脚本以退出码 3 结束。此时：
   - 告诉用户：本次任务的标签页已在浏览器中打开，请点击「去验证」并按提示完成验证。
   - **不要**尝试自动解题、注入脚本、切换账号或使用第三方打码服务。
   - 验证完成后重新运行同一条命令；脚本会复用该标签页（同一 session）。
3. 如果验证页的验证资源本身不可达（例如 `captcha.gtimg.com` 网络不通），移动端回退仍失败时，如实说明当前网络无法完成验证，不要伪造正文。
4. 如果用户无法完成验证，终止任务并如实说明；不要用其他来源冒充文章正文。

### 4. 归档结果

成功后向用户汇报：

- 文章标题、公众号、发布时间
- Markdown 文件路径（主产物）
- JSON / HTML 文件路径（结构化与原始正文）
- 正文字数与图片数量

## Input Contract

| 输入 | 必需 | 说明 |
|---|---:|---|
| `url` | 是 | `mp.weixin.qq.com` 的 `/s/<id>` 或 `/s?__biz=...` 文章链接 |
| `output_dir` | 否 | 输出目录；默认当前工作目录下的 `_raw` |
| `session` | 否 | kimi-webbridge 会话名；默认 `wechat-article-fetch` |
| `daemon_url` | 否 | daemon 地址；默认自动探测或 `KIMI_WEBBRIDGE_URL` |
| `timeout` | 否 | 正文等待秒数；默认 30 |
| `write_html` | 否 | 是否写独立 HTML；默认 `true` |

运行前置条件：

- 本机已安装 kimi-webbridge daemon，且 Kimi 浏览器扩展已连接（`kimi-webbridge status`）。
- 用户浏览器可正常访问微信文章（必要时由用户完成一次人工验证）。

## Output Contract

输出目录（默认 `_raw/`）下写入三个文件，`<stem>` 为稳定标识：

```
_raw/
├── <YYYY-MM-DD>-<slug>-<article_id>.md    # 主产物：YAML frontmatter + Markdown 正文
├── <YYYY-MM-DD>-<slug>-<article_id>.json  # 元数据 + 纯文本正文 + 图片 URL 列表
└── <YYYY-MM-DD>-<slug>-<article_id>.html  # 独立 HTML 文档（可用 --no-html 关闭）
```

命名规则：

- `YYYY-MM-DD` 来自文章发布时间；无法解析时省略日期段。
- `slug` 来自标题，保留中文，非法文件名字符替换为 `-`，最长 60 字符。
- `article_id` 优先取 `/s/<token>`，否则取 `sn` / `mid` / URL 哈希。
- 标题缺失时 slug 回退为 `wechat-article`。
- 同一文章重复抓取会覆盖同名文件（幂等）。

Markdown frontmatter 字段：`title`、`source_url`、`canonical_url`、`account`、
`author`、`publish_time`、`fetched_at`、`session`、`article_id`、`content_sha256`、
`image_count`。

JSON 结构：

```json
{
  "meta": { "...": "frontmatter 同源字段 + output_stem + files" },
  "images": ["https://mmbiz.qpic.cn/..."],
  "content_text": "纯文本正文"
}
```

## Acceptance Criteria

全部满足才算完成：

- [ ] 退出码为 `0`。
- [ ] Markdown 文件存在，以 `---` frontmatter 开头，且包含非空正文。
- [ ] JSON 文件可解析，`meta.title`、`meta.source_url`、`content_text` 与页面一致。
- [ ] 文内图片以 `data-src`（懒加载真实地址）写入 Markdown，未使用占位图。
- [ ] 汇报的路径、字数、图片数与实际文件一致（重新读取文件核对，不复述脚本自报）。
- [ ] 验证页（退出码 3）或不可访问页（退出码 4）如实上报，未编造正文。
- [ ] 未关闭用户的标签页或 kimi-webbridge 会话。

## Failure Handling

| 现象 | 处理 |
|---|---|
| `daemon_unreachable` / 连接被拒 | 运行 `~/.kimi-webbridge/bin/kimi-webbridge start`（Windows: `%USERPROFILE%\.kimi-webbridge\bin\kimi-webbridge.exe`） |
| `extension_not_connected` | 让用户在浏览器中打开 Kimi 侧边栏并启用扩展，然后重试 |
| `navigate: page load timeout` | 脚本会自动接管已打开的标签页；仍失败时增大 `--timeout` |
| 验证页 | 脚本自动切换移动端微信 UA 重试；仍失败则用户人工完成验证后重跑，详见「验证页处理」 |
| 文章已删除/屏蔽 | 退出码 4，如实汇报，不生成空文件 |
| 内容为图片长图 | 正文文本可能很短；图片 URL 仍写入 Markdown/JSON，向用户说明 |

## References

- `references/wechat-extraction.md` — 选择器、页面状态判定、Markdown 转换规则
- `references/path-defaults.yaml` — 默认路径
- `scripts/fetch_wechat_article.py` — 抓取与归档实现
- `scripts/tests/test_fetch_wechat_article.py` — 纯函数单元测试

## External Dependency Metadata

| 依赖 | 类型 | 必需 | 版本 | 用途 |
|---|---|---:|---|---|
| `kimi-webbridge` | SKILL | 是 | `>=2.0` | 通过用户真实浏览器渲染并读取微信文章 |

依赖不可用时不要伪造结果：先按脚本提示恢复 daemon 与扩展连接。
