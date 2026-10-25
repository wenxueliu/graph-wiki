# 微信文章 DOM 提取参考

本文件记录 `scripts/fetch_wechat_article.py` 依赖的选择器与页面状态判定。
微信模板可能调整；出现提取失败时先在这里核对，再更新脚本与测试。

## 页面状态

| 状态 | 判定依据 | 脚本行为 |
|---|---|---|
| `ok` | `#js_content` 存在且 HTML/文本非空 | 归档 |
| `verify` | URL 含 `wappoc_appmsgcaptcha` 或 `secitptpage`，或存在 `#js_verify` | 退出码 3，交给用户人工验证 |
| `unavailable` | 无 `#js_content`，页面文本含「该内容已被发布者删除」「此内容因违规无法查看」「内容已删除」「该公众号已迁移」「已停止访问该网页」 | 退出码 4 |
| `gate` | 无 `#js_content`，页面文本含「请在微信客户端打开」或「环境异常」 | 退出码 4 |
| `pending` | 以上都不满足，正文尚未出现 | 继续轮询直到超时（退出码 5） |

> 不要仅凭「环境异常」四个字判定验证页：正文里也可能出现这个词。
> 优先看 URL 和 `#js_verify`，文本只用于 `gate` / `unavailable` 的兜底分类。

## 环境验证与移动端 UA 回退

微信根据 User-Agent 返回不同页面：

| UA | 结果 |
|---|---|
| 桌面 Chrome / 自动化 UA | 「环境异常」验证页，依赖 `captcha.gtimg.com` |
| 手机微信 UA（`MicroMessenger/8.x`） | 直接渲染文章，URL 追加 `?nwr_flag=1#wechat_redirect` |

脚本检测到 `verify` 状态后：

1. 通过 `Emulation.setUserAgentOverride` 把当前标签页切到 `MOBILE_WECHAT_UA`。
2. 在同一标签页重新导航到文章 URL。
3. 重新轮询 `#js_content`。
4. 归档结束后用空 `userAgent` 重置覆盖，避免影响用户后续浏览。

这是**兼容性回退**，不是验证码破解：不调用打码服务、不伪造 ticket、不修改验证请求。
移动端 UA 仍被挑战时，脚本返回退出码 3，由用户人工完成验证。

## 元数据选择器

| 字段 | 主选择器 | 回退 |
|---|---|---|
| 标题 | `#activity-name` | `.rich_media_title` → `og:title` → `document.title`（去掉「 - 微信公众平台」） |
| 公众号 | `#js_name` | `.rich_media_meta_nickname` → `og:article:author` |
| 作者 | `#js_author_name` | 空 |
| 发布时间 | `#publish_time` | `og:release_date` → `article:published_time` |
| 摘要 | `meta[name="description"]` | `og:description` |
| 封面 | `og:image` | 空 |
| 正文 HTML | `#js_content.innerHTML` | 空 → `pending` |
| 正文文本 | `#js_content.innerText` | `textContent` |
| 图片 | `#js_content img` 的 `data-src` | `src`（可能是占位图，排在 `data-src` 之后） |

## 正文转换规则

- 块级标签（`p`、`div`、`section`、`figure`、`blockquote`、标题等）转为段落间隔。
- `<br>` → 换行；`<hr>` → `---`。
- `strong` / `b` → `**...**`；`em` / `i` → `*...*`；`code` → `` `...` ``。
- `a[href]` → `[text](href)`；`javascript:` 和 `#` 链接只保留文本。
- `img` 优先使用 `data-src`，输出 `![alt](url)`；不下载图片，只保留 URL。
- `ul` / `ol` / `li` → `-` / `1.` 列表。
- 连续空白折叠为单个空格；连续空行压缩为两个换行。
- `innerText` / `textContent` 作为 HTML 转换失败时的兜底正文。

## 已知限制

- 正文全部是长图的文章，纯文本会很短；图片 URL 仍会保留。
- 视频、音频、小程序卡片不在正文文本中，仅保留其周边文字。
- 付费/受限文章只在页面实际渲染正文时才能提取。
- iframe 内容不在 `#js_content` 内，微信文章正文通常不使用 iframe。
