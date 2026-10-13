from __future__ import annotations

from hictc_web_scraper.assets import (
    collect_html_urls,
    cookies_for_url,
    iter_resource_entries,
    rewrite_html_urls,
)

RESOURCE_DATA = {
    "rows": [
        {
            "_id": "r1",
            "origName": "figure1.png",
            "fileUrl": "https://cdn.ehep.com.cn/book/figure1.png",
        },
        {
            "_id": "r2",
            "filename": "lecture.mp4",
            "url": "https://cdn.ehep.com.cn/book/lecture.mp4",
        },
        {"_id": "r3", "name": "no url"},
    ]
}


def test_iter_resource_entries() -> None:
    entries = list(iter_resource_entries(RESOURCE_DATA))
    urls = {url for _, url in entries}
    assert "https://cdn.ehep.com.cn/book/figure1.png" in urls
    assert "https://cdn.ehep.com.cn/book/lecture.mp4" in urls
    assert len(entries) == 2
    names = dict((url, name) for name, url in entries)
    assert names["https://cdn.ehep.com.cn/book/figure1.png"] == "figure1.png"


def test_iter_resource_entries_dedupes() -> None:
    data = {
        "a": {"url": "https://x.test/a.png"},
        "b": {"url": "https://x.test/a.png"},
    }
    assert len(list(iter_resource_entries(data))) == 1


def test_collect_html_urls_resolves_relative() -> None:
    html = '<p><img src="img/a.png"><a href="https://x.test/b.pdf">b</a></p>'
    urls = collect_html_urls(html, "https://ehep.com.cn")
    assert "https://ehep.com.cn/img/a.png" in urls
    assert "https://x.test/b.pdf" in urls


def test_rewrite_html_urls() -> None:
    html = '<p><img src="https://cdn.ehep.com.cn/book/figure1.png"></p>'
    mapping = {"https://cdn.ehep.com.cn/book/figure1.png": "media/figure1.png"}
    rewritten = rewrite_html_urls(html, mapping, "https://ehep.com.cn")
    assert "../media/figure1.png" in rewritten


def test_rewrite_html_urls_keeps_unknown() -> None:
    html = '<p><img src="https://other.test/keep.png"></p>'
    rewritten = rewrite_html_urls(html, {"https://cdn.test/a.png": "media/a.png"}, "https://ehep.com.cn")
    assert "https://other.test/keep.png" in rewritten


def test_rewrite_html_urls_no_mapping() -> None:
    html = "<p>plain</p>"
    assert rewrite_html_urls(html, {}, "https://ehep.com.cn") == html


def test_cookies_for_url_matches_domain() -> None:
    cookies = [
        {"name": "a", "value": "1", "domain": ".shixizhi.huawei.com"},
        {"name": "b", "value": "2", "domain": "talent.shixizhi.huawei.com"},
        {"name": "c", "value": "3", "domain": "other.test"},
    ]
    header = cookies_for_url("https://talent.shixizhi.huawei.com/x", cookies)
    assert "a=1" in header
    assert "b=2" in header
    assert "c=3" not in header


def test_cookies_for_url_empty() -> None:
    assert cookies_for_url("https://x.test", None) == ""
    assert cookies_for_url("https://x.test", []) == ""
