"""Unit tests for the WeChat article archival helpers.

The browser integration is exercised manually against a real article. These
tests cover the pure helpers: URL validation, naming, page classification,
HTML-to-Markdown conversion, and output writing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_wechat_article as fetcher  # noqa: E402


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def test_normalize_url_accepts_token_and_query_forms() -> None:
    assert (
        fetcher.normalize_url("https://mp.weixin.qq.com/s/AbC123")
        == "https://mp.weixin.qq.com/s/AbC123"
    )
    assert (
        fetcher.normalize_url(
            "http://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=2&sn=abc"
        )
        == "https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=2&sn=abc"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/s/AbC123",
        "https://mp.weixin.qq.com/",
        "https://mp.weixin.qq.com/mp/profile_ext?action=home",
        "ftp://mp.weixin.qq.com/s/AbC123",
        "",
    ],
)
def test_normalize_url_rejects_non_article_urls(url: str) -> None:
    with pytest.raises(fetcher.UsageError):
        fetcher.normalize_url(url)


def test_article_id_prefers_readable_identifiers() -> None:
    assert fetcher.article_id("https://mp.weixin.qq.com/s/AbC_123") == "AbC_123"
    assert (
        fetcher.article_id(
            "https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=2&sn=deadbeef"
        )
        == "deadbeef"
    )


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def test_slugify_keeps_cjk_and_removes_unsafe_characters() -> None:
    assert fetcher.slugify("  Hello: 世界 / Test  ") == "Hello-世界-Test"
    assert fetcher.slugify("《一个人住的第五年》") == "一个人住的第五年"
    assert fetcher.slugify("a" * 100, max_length=20) == "a" * 20
    assert fetcher.slugify("///") == ""


def test_parse_publish_date_supports_common_wechat_formats() -> None:
    assert fetcher.parse_publish_date("2025年3月9日") == "2025-03-09"
    assert fetcher.parse_publish_date("2025-03-09 10:00") == "2025-03-09"
    assert fetcher.parse_publish_date("2025/3/9") == "2025-03-09"
    assert fetcher.parse_publish_date("昨天") == ""
    assert fetcher.parse_publish_date("2025年13月40日") == ""


def test_build_stem_combines_date_title_and_identifier() -> None:
    extraction = {"title": "测试文章", "publishTime": "2025年3月9日"}
    stem = fetcher.build_stem(
        extraction, "https://mp.weixin.qq.com/s/AbC123"
    )
    assert stem == "2025-03-09-测试文章-AbC123"


def test_build_stem_falls_back_when_title_is_missing() -> None:
    stem = fetcher.build_stem({}, "https://mp.weixin.qq.com/s/AbC123")
    assert stem == "wechat-article-AbC123"


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------


def test_classify_detects_anti_bot_verification() -> None:
    assert fetcher.classify({"verify": True, "ok": False}) == "verify"
    assert (
        fetcher.classify({"verify": False, "unavailable": True, "ok": False})
        == "unavailable"
    )
    assert (
        fetcher.classify({"verify": False, "clientGate": True, "ok": False})
        == "gate"
    )


def test_classify_requires_actual_content_for_ok() -> None:
    assert (
        fetcher.classify({"ok": True, "contentHtml": "<p>正文</p>", "contentText": "正文"})
        == "ok"
    )
    assert fetcher.classify({"ok": True, "contentHtml": "", "contentText": ""}) == "pending"
    assert fetcher.classify({"ok": False}) == "pending"


# ---------------------------------------------------------------------------
# HTML -> Markdown
# ---------------------------------------------------------------------------


def test_html_to_markdown_preserves_inline_formatting_and_links() -> None:
    content = (
        "<section><p>你好 <strong>世界</strong>，<em>这是</em>测试。</p>"
        '<p><a href="https://example.com">链接</a></p></section>'
    )
    markdown = fetcher.html_to_markdown(content)
    assert "你好 **世界**，*这是*测试。" in markdown
    assert "[链接](https://example.com)" in markdown
    assert "\n\n" in markdown


def test_html_to_markdown_uses_lazy_image_source() -> None:
    content = (
        '<p><img data-src="https://mmbiz.qpic.cn/real.png" '
        'src="https://mmbiz.qpic.cn/placeholder.png"></p>'
    )
    markdown = fetcher.html_to_markdown(content)
    assert "![image](https://mmbiz.qpic.cn/real.png)" in markdown
    assert "placeholder.png" not in markdown


def test_html_to_markdown_renders_lists_and_breaks() -> None:
    content = "<p>第一行<br>第二行</p><ul><li>甲</li><li>乙</li></ul>"
    markdown = fetcher.html_to_markdown(content)
    assert "第一行\n第二行" in markdown
    assert "- 甲" in markdown
    assert "- 乙" in markdown


def test_html_to_markdown_drops_javascript_links() -> None:
    markdown = fetcher.html_to_markdown(
        '<p><a href="javascript:;">扫码关注</a></p>'
    )
    assert "[扫码关注]" in markdown
    assert "javascript:" not in markdown


def test_html_to_markdown_keeps_linked_images_inline() -> None:
    content = (
        '<p><a href="https://mp.weixin.qq.com/s/next">'
        '<img data-src="https://mmbiz.qpic.cn/real.png"></a></p>'
    )
    markdown = fetcher.html_to_markdown(content)
    assert (
        "[![image](https://mmbiz.qpic.cn/real.png)]"
        "(https://mp.weixin.qq.com/s/next)" in markdown
    )
    # No blank line may split the link text from its image.
    assert "[\n" not in markdown


def test_html_to_markdown_removes_empty_headings() -> None:
    markdown = fetcher.html_to_markdown("<h3></h3><p>正文</p>")
    assert markdown == "正文"


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

EXTRACTION = {
    "ok": True,
    "href": "https://mp.weixin.qq.com/s/AbC123",
    "title": "测试文章",
    "account": "测试公众号",
    "author": "作者甲",
    "publishTime": "2025年3月9日",
    "description": "摘要",
    "coverImage": "https://mmbiz.qpic.cn/cover.png",
    "contentHtml": "<p>正文 <strong>加粗</strong></p>",
    "contentText": "正文 加粗",
    "images": ["https://mmbiz.qpic.cn/real.png"],
}


def test_write_outputs_creates_markdown_json_and_html(tmp_path: Path) -> None:
    result = fetcher.write_outputs(
        EXTRACTION,
        "https://mp.weixin.qq.com/s/AbC123",
        tmp_path,
        "test-session",
    )

    expected_stem = "2025-03-09-测试文章-AbC123"
    markdown_path = tmp_path / f"{expected_stem}.md"
    json_path = tmp_path / f"{expected_stem}.json"
    html_path = tmp_path / f"{expected_stem}.html"

    assert result["stem"] == expected_stem
    assert markdown_path.is_file()
    assert json_path.is_file()
    assert html_path.is_file()

    markdown = markdown_path.read_text(encoding="utf-8")
    assert markdown.startswith("---\n")
    assert 'title: "测试文章"' in markdown
    assert 'account: "测试公众号"' in markdown
    assert "# 测试文章" in markdown
    assert "正文 **加粗**" in markdown
    assert "> 原文: https://mp.weixin.qq.com/s/AbC123" in markdown

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["meta"]["output_stem"] == expected_stem
    assert payload["meta"]["image_count"] == 1
    assert payload["images"] == ["https://mmbiz.qpic.cn/real.png"]
    assert payload["content_text"] == "正文 加粗"

    html_doc = html_path.read_text(encoding="utf-8")
    assert "<article id=\"wechat-content\">" in html_doc
    assert "正文 <strong>加粗</strong>" in html_doc


def test_write_outputs_can_skip_html(tmp_path: Path) -> None:
    result = fetcher.write_outputs(
        EXTRACTION,
        "https://mp.weixin.qq.com/s/AbC123",
        tmp_path,
        "test-session",
        write_html=False,
    )

    assert len(result["files"]) == 2
    assert not (tmp_path / f"{result['stem']}.html").exists()
