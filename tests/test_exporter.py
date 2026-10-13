from __future__ import annotations

import json

from hictc_web_scraper.exporter import (
    build_chapter_document,
    extract_content_html,
    find_html_in_json,
    html_to_text,
    slugify,
)


def test_extract_content_html_raw_html() -> None:
    raw = "<div><p>Hello</p></div>"
    assert extract_content_html(raw) == raw


def test_extract_content_html_from_json() -> None:
    raw = json.dumps({"id": "1", "content": "<div><p>Hello</p></div>"})
    assert extract_content_html(raw) == "<div><p>Hello</p></div>"


def test_extract_content_html_prefers_longest() -> None:
    raw = json.dumps(
        {
            "title": "<p>tiny</p>",
            "body": {"html": "<p>" + "word " * 50 + "</p>"},
        }
    )
    result = extract_content_html(raw)
    assert result.startswith("<p>word")
    assert len(result) > 100


def test_extract_content_html_non_html_json_returns_raw() -> None:
    raw = json.dumps({"code": 200, "message": "ok"})
    assert extract_content_html(raw) == raw


def test_find_html_in_json_none() -> None:
    assert find_html_in_json({"a": "plain text"}) is None


def test_slugify() -> None:
    assert slugify("Chapter 1: Introduction!") == "chapter-1-introduction"
    assert slugify("") == "section"
    assert slugify("数据表管理") == "数据表管理"


def test_build_chapter_document_escapes_title() -> None:
    document = build_chapter_document("<script>x</script>", "<p>body</p>", ["A", "B"])
    assert "<script>x</script>" not in document
    assert "&lt;script&gt;" in document
    assert "<p>body</p>" in document


def test_html_to_text() -> None:
    text = html_to_text("<div><p>One</p><p>Two</p></div>")
    assert "One" in text
    assert "Two" in text
