#!/usr/bin/env python3
"""Fetch a WeChat Official Account article through kimi-webbridge.

The script drives the user's real browser through the local kimi-webbridge
daemon, reads the rendered article DOM, and archives the result as Markdown +
JSON (+ optional standalone HTML) under ``_raw/``.

Why a real browser: mp.weixin.qq.com serves anti-bot verification pages to
plain HTTP clients. The user's browser session is the only supported way to
read the article after the human completes that verification.

Usage:
    python fetch_wechat_article.py https://mp.weixin.qq.com/s/XXXX
    python fetch_wechat_article.py https://mp.weixin.qq.com/s/XXXX -o _raw
    python fetch_wechat_article.py https://mp.weixin.qq.com/s/XXXX --json

Exit codes:
    0  Article archived successfully
    2  Invalid arguments or unsupported URL
    3  WeChat anti-bot verification required (human action needed)
    4  Article unavailable (deleted, blocked, migrated, or client-gated)
    5  Extraction timed out (page loaded but article DOM not found)
    6  kimi-webbridge daemon or browser extension unavailable
    7  Output could not be written
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

DEFAULT_DAEMON = "http://127.0.0.1:10086"
DEFAULT_SESSION = "wechat-article-fetch"
DEFAULT_OUTPUT_DIR = "_raw"
DEFAULT_TIMEOUT = 30.0
WECHAT_HOST = "mp.weixin.qq.com"

# WeChat serves the "环境异常" challenge to desktop/automation user agents but
# renders the article normally for its mobile client. Switching the tab to the
# mobile UA is a compatibility fallback, not a captcha solver: when the
# challenge still appears, the human hand-off path (exit code 3) is used.
MOBILE_WECHAT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.44(0x18002c2f) NetType/WIFI Language/zh_CN"
)
MOBILE_UA_OVERRIDE = {
    "userAgent": MOBILE_WECHAT_UA,
    "acceptLanguage": "zh-CN,zh;q=0.9",
    "platform": "iPhone",
}

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FetchError(Exception):
    """Base error carrying an exit code and a user-facing message."""

    exit_code = 1

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class UsageError(FetchError):
    exit_code = 2


class VerificationRequired(FetchError):
    exit_code = 3


class ArticleUnavailable(FetchError):
    exit_code = 4


class ExtractionTimeout(FetchError):
    exit_code = 5


class BridgeUnavailable(FetchError):
    exit_code = 6


class OutputError(FetchError):
    exit_code = 7


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def normalize_url(raw: str) -> str:
    """Validate and normalize a mp.weixin.qq.com article URL."""
    raw = (raw or "").strip()
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise UsageError(f"URL 必须以 http:// 或 https:// 开头: {raw!r}")
    if parsed.hostname != WECHAT_HOST:
        raise UsageError(
            f"只支持 mp.weixin.qq.com 的文章链接，收到: {parsed.hostname or raw!r}"
        )
    if not (parsed.path == "/s" or parsed.path.startswith("/s/")):
        raise UsageError(
            "只支持 /s/<id> 或 /s?__biz=... 形式的公众号文章链接: "
            f"{parsed.path or '/'}"
        )
    return urllib.parse.urlunsplit(("https", WECHAT_HOST, parsed.path, parsed.query, ""))


def article_id(url: str) -> str:
    """Return a stable short identifier for an article URL."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.path.startswith("/s/"):
        token = parsed.path.rsplit("/", 1)[-1]
        token = re.sub(r"[^A-Za-z0-9_-]", "", token)
        if token:
            return token[:24]
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("sn", "mid", "idx", "__biz"):
        value = (query.get(key) or [""])[0]
        value = re.sub(r"[^A-Za-z0-9_-]", "", value)
        if value:
            return value[:24]
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def article_keys(url: str) -> list[str]:
    """Keys used to find the article tab after a navigation timeout."""
    parsed = urllib.parse.urlsplit(url)
    keys: list[str] = []
    if parsed.path.startswith("/s/"):
        token = parsed.path.rsplit("/", 1)[-1]
        if token:
            keys.append(token)
    query = urllib.parse.parse_qs(parsed.query)
    mid = (query.get("mid") or [""])[0]
    idx = (query.get("idx") or [""])[0]
    if mid:
        keys.append(mid)
        if idx:
            keys.append(f"mid={mid}&idx={idx}")
    if not keys:
        keys.append(article_id(url))
    return keys


# ---------------------------------------------------------------------------
# Daemon client
# ---------------------------------------------------------------------------


def _daemon_binary() -> Path:
    name = "kimi-webbridge.exe" if os.name == "nt" else "kimi-webbridge"
    return Path.home() / ".kimi-webbridge" / "bin" / name


def _run_bridge_cli(*args: str, timeout: float = 30.0) -> str:
    binary = _daemon_binary()
    if not binary.exists():
        raise BridgeUnavailable(
            "未找到 kimi-webbridge 可执行文件。",
            detail=(
                "请先在 Kimi 浏览器扩展帮助页安装 Kimi Browser Extension：\n"
                "  中文: https://www.kimi.com/products/kimi-webbridge\n"
                "  English: https://www.kimi.com/en/products/kimi-webbridge"
            ),
        )
    try:
        proc = subprocess.run(
            [str(binary), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeUnavailable(f"无法执行 kimi-webbridge {args[0]}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise BridgeUnavailable(f"kimi-webbridge {args[0]} 失败。", detail=detail)
    return proc.stdout


def _status_json() -> dict[str, Any]:
    output = _run_bridge_cli("status", timeout=15.0)
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "running" in payload:
            return payload
    raise BridgeUnavailable(
        "kimi-webbridge status 返回了无法解析的内容。",
        detail=output.strip()[:1000],
    )


def resolve_daemon(explicit: str | None) -> str:
    """Resolve the daemon base URL, starting the daemon if needed."""
    if explicit:
        return explicit.rstrip("/")

    env_url = os.environ.get("KIMI_WEBBRIDGE_URL")
    if env_url:
        return env_url.rstrip("/")

    status = _status_json()
    if not status.get("running"):
        _run_bridge_cli("start", timeout=45.0)
        status = _status_json()
    port = status.get("port")
    if not status.get("running") or not port:
        raise BridgeUnavailable(
            "kimi-webbridge daemon 未能启动。",
            detail=json.dumps(status, ensure_ascii=False),
        )
    return f"http://127.0.0.1:{int(port)}"


class BridgeClient:
    """Minimal client for the kimi-webbridge /command endpoint."""

    def __init__(self, base_url: str, *, http_timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.http_timeout = http_timeout

    def command(self, action: str, args: dict[str, Any] | None = None,
                session: str = DEFAULT_SESSION) -> dict[str, Any]:
        payload = json.dumps(
            {"action": action, "args": args or {}, "session": session},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/command",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The daemon reports protocol errors as an HTTP error whose body
            # still carries the {ok:false, error:{...}} envelope.
            body = exc.read().decode("utf-8", "replace")
            try:
                envelope = json.loads(body)
            except json.JSONDecodeError:
                raise BridgeUnavailable(
                    f"kimi-webbridge 返回 HTTP {exc.code}。",
                    detail=body[:1000],
                ) from exc
        except urllib.error.URLError as exc:
            raise BridgeUnavailable(
                f"无法连接 kimi-webbridge daemon ({self.base_url})。",
                detail=str(exc),
            ) from exc
        except json.JSONDecodeError as exc:
            raise BridgeUnavailable(
                f"kimi-webbridge 返回了非 JSON 响应 ({self.base_url})。",
                detail=str(exc),
            ) from exc

        if not isinstance(envelope, dict) or "ok" not in envelope:
            raise BridgeUnavailable(
                "kimi-webbridge 返回了未知响应格式。",
                detail=json.dumps(envelope, ensure_ascii=False)[:1000],
            )
        if not envelope.get("ok"):
            error = envelope.get("error") or {}
            code = str(error.get("code", "unknown"))
            message = str(error.get("message", "unknown error"))
            if code == "extension_not_connected":
                raise BridgeUnavailable(
                    "Kimi 浏览器扩展未连接。请打开浏览器中的 Kimi 侧边栏，",
                    detail=message,
                )
            raise BridgeUnavailable(
                f"kimi-webbridge 调用 {action} 失败: {code}: {message}"
            )
        data = envelope.get("data")
        return data if isinstance(data, dict) else {}


def ensure_extension(client: BridgeClient) -> None:
    """Fail early with a clear message when the extension is disconnected."""
    try:
        with urllib.request.urlopen(f"{client.base_url}/status", timeout=10) as response:
            status = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return  # /status is optional; the first command will report clearly.
    if status.get("running") and status.get("extension_connected") is False:
        raise BridgeUnavailable(
            "Kimi 浏览器扩展未连接。请打开浏览器中的 Kimi 侧边栏并确认扩展已启用。"
        )


# ---------------------------------------------------------------------------
# Page extraction
# ---------------------------------------------------------------------------

EXTRACT_JS = r"""
(() => {
  const textOf = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return "";
    return (el.innerText || el.textContent || "").trim();
  };
  const metaOf = (name) => {
    const el = document.querySelector('meta[property="' + name + '"]')
      || document.querySelector('meta[name="' + name + '"]');
    return el ? (el.getAttribute("content") || "").trim() : "";
  };

  const body = document.querySelector("#js_content");
  const pageText = ((document.body && document.body.innerText) || "").slice(0, 4000);
  const verify = /wappoc_appmsgcaptcha|secitptpage/i.test(location.href)
    || !!document.querySelector("#js_verify");
  const unavailable = !body && /该内容已被发布者删除|此内容因违规无法查看|内容已删除|该公众号已迁移|已停止访问该网页|无法查看/.test(pageText);
  const clientGate = !body && /请在微信客户端打开|环境异常/.test(pageText);

  const images = [];
  if (body) {
    body.querySelectorAll("img").forEach((img) => {
      const src = img.getAttribute("data-src") || img.getAttribute("src") || "";
      if (src) images.push(src);
    });
  }

  const title = textOf("#activity-name")
    || textOf(".rich_media_title")
    || metaOf("og:title")
    || (document.title || "").replace(/\s*[-–—]\s*微信公众平台\s*$/, "").trim();
  const account = textOf("#js_name") || textOf(".rich_media_meta_nickname")
    || metaOf("og:article:author");
  const author = textOf("#js_author_name");
  const publishTime = textOf("#publish_time")
    || metaOf("og:release_date")
    || metaOf("article:published_time");

  return JSON.stringify({
    ok: !!body,
    href: location.href,
    title: title,
    account: account,
    author: author,
    publishTime: publishTime,
    description: metaOf("description") || metaOf("og:description"),
    coverImage: metaOf("og:image"),
    verify: verify,
    unavailable: unavailable,
    clientGate: clientGate,
    contentHtml: body ? body.innerHTML : "",
    contentText: body ? (body.innerText || body.textContent || "") : "",
    images: images,
    pageText: body ? "" : pageText
  });
})()
"""


def classify(extraction: dict[str, Any]) -> str:
    """Classify one extraction snapshot: ok | verify | unavailable | gate | pending."""
    if extraction.get("verify"):
        return "verify"
    if extraction.get("unavailable"):
        return "unavailable"
    if extraction.get("clientGate"):
        return "gate"
    if extraction.get("ok") and (
        str(extraction.get("contentHtml") or "").strip()
        or str(extraction.get("contentText") or "").strip()
    ):
        return "ok"
    return "pending"


def _attach_matching_tab(client: BridgeClient, url: str, session: str) -> None:
    """Attach the browser tab whose URL belongs to this article."""
    tabs = client.command("list_browser_tabs", {}, session).get("tabs") or []
    keys = article_keys(url)
    candidates = []
    for tab in tabs:
        tab_url = str(tab.get("url") or "")
        decoded = urllib.parse.unquote(tab_url)
        if any(key and key in decoded for key in keys):
            candidates.append(tab)
    if not candidates:
        raise ExtractionTimeout(
            "导航超时，且未能在浏览器中找到目标文章标签页。",
            detail=f"session={session} url={url}",
        )
    candidates.sort(key=lambda tab: "wappoc_appmsgcaptcha" in str(tab.get("url") or ""))
    client.command("attach_tab", {"tabId": candidates[0]["tabId"]}, session)


def _navigate(client: BridgeClient, url: str, session: str, *, new_tab: bool) -> None:
    """Navigate, recovering the tab when the page's load event times out."""
    args: dict[str, Any] = {"url": url, "newTab": new_tab}
    if new_tab:
        args["group_title"] = "微信文章抓取"
    try:
        client.command("navigate", args, session)
        return
    except BridgeUnavailable as exc:
        if "timeout" not in (exc.message + exc.detail).lower():
            raise

    # WeChat keeps long-poll connections open, so `load` can time out even
    # though the article is already rendered. Find and attach the tab.
    _attach_matching_tab(client, url, session)


def navigate_to_article(client: BridgeClient, url: str, session: str) -> None:
    _navigate(client, url, session, new_tab=True)


def _set_user_agent(client: BridgeClient, session: str,
                    params: dict[str, str]) -> None:
    client.command(
        "cdp",
        {"method": "Emulation.setUserAgentOverride", "params": params},
        session,
    )


def reload_with_mobile_user_agent(client: BridgeClient, url: str,
                                  session: str) -> None:
    """Retry the article as a mobile WeChat client when the desktop UA is challenged."""
    _set_user_agent(client, session, MOBILE_UA_OVERRIDE)
    _navigate(client, url, session, new_tab=False)


def restore_user_agent(client: BridgeClient, session: str) -> None:
    """Best-effort reset of the per-tab UA override."""
    try:
        _set_user_agent(client, session, {"userAgent": ""})
    except FetchError:
        pass


def wait_for_article(client: BridgeClient, url: str, session: str,
                     timeout: float) -> dict[str, Any]:
    """Poll the current tab until the article DOM is readable."""
    deadline = time.monotonic() + max(timeout, 1.0)
    last: dict[str, Any] = {"ok": False}
    while True:
        try:
            data = client.command("evaluate", {"code": EXTRACT_JS}, session)
            value = data.get("value")
            extraction = json.loads(value) if isinstance(value, str) else {}
        except BridgeUnavailable as exc:
            if "无法连接" in exc.message or "扩展未连接" in exc.message:
                raise
            # A tab that navigated mid-poll is transient; keep waiting.
            extraction = {"ok": False, "pageText": str(exc)}
        except json.JSONDecodeError as exc:
            extraction = {"ok": False, "pageText": str(exc)}

        if isinstance(extraction, dict) and extraction:
            last = extraction
            state = classify(extraction)
            if state == "verify":
                raise VerificationRequired(
                    "微信要求完成环境验证。请在浏览器中打开本次任务的标签页，"
                    "点击「去验证」并按提示完成验证，然后重新运行本命令。",
                    detail=(
                        f"tab_url={extraction.get('href', '')}\n"
                        f"session={session}\n"
                        "提示：验证完成后标签页会保持打开，脚本会复用它。"
                    ),
                )
            if state == "unavailable":
                raise ArticleUnavailable(
                    "文章当前不可访问（已删除、被屏蔽、迁移或停止访问）。",
                    detail=str(extraction.get("pageText", ""))[:500],
                )
            if state == "gate":
                raise ArticleUnavailable(
                    "微信返回了客户端访问限制页，无法在桌面浏览器中读取正文。",
                    detail=str(extraction.get("pageText", ""))[:500],
                )
            if state == "ok":
                return extraction

        if time.monotonic() >= deadline:
            raise ExtractionTimeout(
                f"等待 {timeout:g} 秒后仍未读取到文章正文。",
                detail=(
                    f"url={url}\n"
                    f"current_url={last.get('href', '')}\n"
                    f"page_text={str(last.get('pageText', ''))[:500]}"
                ),
            )
        time.sleep(1.0)


# ---------------------------------------------------------------------------
# HTML -> Markdown
# ---------------------------------------------------------------------------


class _MarkdownParser(HTMLParser):
    """Small HTML-to-Markdown converter tuned for WeChat article HTML."""

    BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer", "figure",
        "figcaption", "blockquote", "pre", "table", "tr", "h1", "h2", "h3",
        "h4", "h5", "h6",
    }
    HEADING_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[str] = []
        self.link_stack: list[dict[str, str]] = []
        self.pre_depth = 0
        self.table_cell: list[str] = []

    # -- helpers ---------------------------------------------------------
    def _append(self, text: str) -> None:
        self.parts.append(text)

    def _newline(self, count: int = 2) -> None:
        current = "".join(self.parts[-3:])
        if current.endswith("\n\n"):
            return
        if current.endswith("\n"):
            if count >= 2:
                self._append("\n")
            return
        self._append("\n" * count)

    def _list_marker(self) -> str:
        if not self.list_stack:
            return ""
        if self.list_stack[-1] == "ol":
            return "1. "
        return "- "

    # -- HTMLParser hooks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        tag = tag.lower()

        if tag == "br":
            self._append("\n")
            return
        if tag == "hr":
            self._newline(2)
            self._append("---")
            self._newline(2)
            return
        if tag == "img":
            src = attributes.get("data-src") or attributes.get("src") or ""
            if src:
                alt = attributes.get("alt") or "image"
                image = f"![{alt}]({src})"
                if self.link_stack:
                    # A linked image must stay inline: Markdown link text
                    # cannot contain a blank line.
                    self._append(image)
                else:
                    self._newline(2)
                    self._append(image)
                    self._newline(2)
            return
        if tag == "a":
            self.link_stack.append({"href": attributes.get("href", "")})
            self._append("[")
            return
        if tag in {"strong", "b"}:
            self._append("**")
            return
        if tag in {"em", "i"}:
            self._append("*")
            return
        if tag == "code":
            self._append("`")
            return
        if tag == "pre":
            self.pre_depth += 1
            self._newline(2)
            self._append("```\n")
            return
        if tag in {"ul", "ol"}:
            self._newline(1)
            self.list_stack.append(tag)
            return
        if tag == "li":
            self._newline(1)
            self._append(self._list_marker())
            return
        if tag in self.HEADING_TAGS:
            self._newline(2)
            self._append(self.HEADING_TAGS[tag] + " ")
            return
        if tag == "blockquote":
            self._newline(2)
            self._append("> ")
            return
        if tag == "tr":
            self._newline(1)
            return
        if tag in {"td", "th"}:
            if self.table_cell:
                self._append(" | ")
            return
        if tag in self.BLOCK_TAGS:
            self._newline(2)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a":
            link = self.link_stack.pop() if self.link_stack else {"href": ""}
            href = link.get("href", "")
            if href and not href.lower().startswith(("javascript:", "#")):
                self._append(f"]({href})")
            else:
                self._append("]")
            return
        if tag in {"strong", "b"}:
            self._append("**")
            return
        if tag in {"em", "i"}:
            self._append("*")
            return
        if tag == "code":
            self._append("`")
            return
        if tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
            self._append("\n```")
            self._newline(2)
            return
        if tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self._newline(2)
            return
        if tag == "li":
            self._newline(1)
            return
        if tag in self.HEADING_TAGS:
            self._newline(2)
            return
        if tag == "blockquote":
            self._newline(2)
            return
        if tag == "tr":
            self._newline(1)
            return
        if tag in {"td", "th"}:
            return
        if tag in self.BLOCK_TAGS:
            self._newline(2)

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self.pre_depth:
            self._append(data)
            return
        text = data.replace("\xa0", " ")
        text = re.sub(r"[ \t\r\n]+", " ", text)
        if not text:
            return
        if not self.parts or self.parts[-1].endswith((" ", "\n", "**", "*", "`", "[")):
            text = text.lstrip()
        self._append(text)


def html_to_markdown(content_html: str) -> str:
    """Convert WeChat article HTML into readable Markdown."""
    if not content_html:
        return ""
    parser = _MarkdownParser()
    parser.feed(content_html)
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(?m)^#{1,6}[ \t]*$\n?", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Naming and output
# ---------------------------------------------------------------------------


def slugify(value: str, *, max_length: int = 60) -> str:
    """Create a filesystem-safe stem that keeps CJK characters readable."""
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"[^\w㐀-䶿一-鿿-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-_ .")
    value = value[:max_length].strip("-_ .")
    return value


def parse_publish_date(value: str) -> str:
    """Return YYYY-MM-DD when the publish time contains a recognizable date."""
    match = re.search(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})", value or "")
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def build_stem(extraction: dict[str, Any], url: str) -> str:
    """Build a deterministic, collision-resistant output stem."""
    title = str(extraction.get("title") or "").strip() or "wechat-article"
    slug = slugify(title) or "wechat-article"
    date = parse_publish_date(str(extraction.get("publishTime") or ""))
    identifier = article_id(url)
    stem = f"{date}-{slug}-{identifier}" if date else f"{slug}-{identifier}"
    stem = stem[:160].strip("-_ .")
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if stem.upper() in reserved:
        stem = f"_{stem}"
    return stem or f"wechat-article-{identifier}"


def _yaml_string(value: str) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def render_markdown(extraction: dict[str, Any], url: str, session: str,
                    stem: str) -> str:
    title = str(extraction.get("title") or "").strip()
    account = str(extraction.get("account") or "").strip()
    author = str(extraction.get("author") or "").strip()
    publish_time = str(extraction.get("publishTime") or "").strip()
    content_html = str(extraction.get("contentHtml") or "")
    content_text = str(extraction.get("contentText") or "")
    images = [str(item) for item in extraction.get("images") or [] if item]
    digest = hashlib.sha256(
        (content_html or content_text).encode("utf-8")
    ).hexdigest()

    body = html_to_markdown(content_html) or content_text.strip()
    frontmatter = [
        "---",
        f"title: {_yaml_string(title)}",
        f"source_url: {_yaml_string(url)}",
        f"canonical_url: {_yaml_string(str(extraction.get('href') or url))}",
        f"account: {_yaml_string(account)}",
        f"author: {_yaml_string(author)}",
        f"publish_time: {_yaml_string(publish_time)}",
        f"fetched_at: {_yaml_string(datetime.now(timezone.utc).isoformat(timespec='seconds'))}",
        f"session: {_yaml_string(session)}",
        f"article_id: {_yaml_string(article_id(url))}",
        f"content_sha256: {_yaml_string(digest)}",
        f"image_count: {len(images)}",
        "---",
        "",
    ]
    lines = [f"# {title}" if title else f"# 微信文章 {article_id(url)}"]
    meta_bits = []
    if account:
        meta_bits.append(f"公众号: {account}")
    if author:
        meta_bits.append(f"作者: {author}")
    if publish_time:
        meta_bits.append(f"发布时间: {publish_time}")
    if meta_bits:
        lines.append("")
        lines.append("> " + " · ".join(meta_bits))
    lines.append(f"> 原文: {url}")
    lines.append("")
    lines.append(body)
    return "\n".join(frontmatter + lines).rstrip() + "\n"


def render_html(extraction: dict[str, Any], url: str) -> str:
    title = html.escape(str(extraction.get("title") or "微信文章"))
    source = html.escape(url, quote=True)
    content = str(extraction.get("contentHtml") or "")
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        f'<meta name="source" content="{source}">\n'
        "<style>body{max-width:760px;margin:2rem auto;padding:0 1rem;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',sans-serif;line-height:1.75;"
        "color:#222}img{max-width:100%;height:auto}</style>\n"
        "</head>\n<body>\n"
        f'<article id="wechat-content">\n{content}\n</article>\n'
        "</body>\n</html>\n"
    )


def write_outputs(extraction: dict[str, Any], url: str, output_dir: Path,
                  session: str, *, write_html: bool = True) -> dict[str, Any]:
    stem = build_stem(extraction, url)
    output_dir = output_dir.expanduser().resolve()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"无法创建输出目录: {output_dir}", detail=str(exc)) from exc

    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    html_path = output_dir / f"{stem}.html"

    images = [str(item) for item in extraction.get("images") or [] if item]
    content_html = str(extraction.get("contentHtml") or "")
    content_text = str(extraction.get("contentText") or "")
    payload = {
        "meta": {
            "title": str(extraction.get("title") or ""),
            "source_url": url,
            "canonical_url": str(extraction.get("href") or url),
            "account": str(extraction.get("account") or ""),
            "author": str(extraction.get("author") or ""),
            "publish_time": str(extraction.get("publishTime") or ""),
            "description": str(extraction.get("description") or ""),
            "cover_image": str(extraction.get("coverImage") or ""),
            "article_id": article_id(url),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session": session,
            "output_stem": stem,
            "image_count": len(images),
            "content_sha256": hashlib.sha256(
                (content_html or content_text).encode("utf-8")
            ).hexdigest(),
            "files": {
                "markdown": markdown_path.name,
                "json": json_path.name,
                "html": html_path.name if write_html else None,
            },
        },
        "images": images,
        "content_text": content_text,
    }

    try:
        markdown_path.write_text(
            render_markdown(extraction, url, session, stem), encoding="utf-8"
        )
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if write_html:
            html_path.write_text(render_html(extraction, url), encoding="utf-8")
    except OSError as exc:
        raise OutputError(f"写入文章文件失败: {output_dir}", detail=str(exc)) from exc

    written = [str(markdown_path), str(json_path)]
    if write_html:
        written.append(str(html_path))
    return {
        "stem": stem,
        "files": written,
        "title": payload["meta"]["title"],
        "content_chars": len(content_text),
        "image_count": len(images),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def fetch(url: str, *, output_dir: Path, session: str, daemon_url: str | None,
          timeout: float, write_html: bool,
          mobile_fallback: bool = True) -> dict[str, Any]:
    normalized = normalize_url(url)
    daemon = resolve_daemon(daemon_url)
    client = BridgeClient(daemon)
    ensure_extension(client)
    navigate_to_article(client, normalized, session)

    ua_overridden = False
    try:
        try:
            extraction = wait_for_article(client, normalized, session, timeout)
        except VerificationRequired as first:
            if not mobile_fallback:
                raise
            try:
                reload_with_mobile_user_agent(client, normalized, session)
                ua_overridden = True
                extraction = wait_for_article(client, normalized, session, timeout)
            except VerificationRequired:
                raise VerificationRequired(
                    first.message,
                    detail=(
                        f"{first.detail}\n"
                        "已尝试切换移动端微信 UA 重试，仍然返回验证页。"
                    ),
                ) from first
            except BridgeUnavailable as exc:
                raise VerificationRequired(
                    first.message,
                    detail=f"{first.detail}\n移动端 UA 回退失败: {exc.message}",
                ) from first
    finally:
        if ua_overridden:
            restore_user_agent(client, session)

    return write_outputs(
        extraction, normalized, output_dir, session, write_html=write_html
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过 kimi-webbridge 抓取微信公众号文章并归档到 _raw/。",
    )
    parser.add_argument("url", help="mp.weixin.qq.com 文章链接")
    parser.add_argument(
        "-o", "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认: {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--session", default=DEFAULT_SESSION,
        help=f"kimi-webbridge 会话名（默认: {DEFAULT_SESSION}）",
    )
    parser.add_argument(
        "--daemon-url", default=None,
        help="daemon 地址（默认自动探测，或读 KIMI_WEBBRIDGE_URL）",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"等待正文出现的最长秒数（默认: {DEFAULT_TIMEOUT:g}）",
    )
    parser.add_argument(
        "--no-html", action="store_true", help="不写独立 HTML 文件",
    )
    parser.add_argument(
        "--no-mobile-fallback", action="store_true",
        help="遇到环境验证页时不自动切换移动端微信 UA",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="以 JSON 输出结果，便于脚本消费",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = fetch(
            args.url,
            output_dir=Path(args.output_dir),
            session=args.session,
            daemon_url=args.daemon_url,
            timeout=args.timeout,
            write_html=not args.no_html,
            mobile_fallback=not args.no_mobile_fallback,
        )
    except FetchError as exc:
        if args.json_output:
            print(json.dumps(
                {"ok": False, "exit_code": exc.exit_code, "error": exc.message,
                 "detail": exc.detail},
                ensure_ascii=False,
            ))
        else:
            print(f"错误: {exc.message}", file=sys.stderr)
            if exc.detail:
                print(exc.detail, file=sys.stderr)
        return exc.exit_code

    if args.json_output:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    else:
        print(f"已保存: {result['title'] or result['stem']}")
        for path in result["files"]:
            print(f"  - {path}")
        print(f"正文 {result['content_chars']} 字，图片 {result['image_count']} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
