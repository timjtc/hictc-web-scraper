from __future__ import annotations

import gzip
from urllib.parse import parse_qs, urlparse

from hictc_web_scraper.edm import (
    collect_edm_sources,
    decode_page,
    parse_edm_src,
)
from hictc_web_scraper.edm import _filename_from_disposition

SRC = (
    "https://talent.shixizhi.huawei.com/edm3client/static/index.html"
    "?lang=en_US&showDownload=hide"
    "&appid=881715bf5fd14684a8e95f6a904f869e"
    "&docVersion=V1&docId=M1T9A107N954045138109755602"
    "&oldPageNum=1&initPageNum=48"
    "&PMurl=https://talent.shixizhi.huawei.com"
    "&baseurl=https://talent.shixizhi.huawei.com/"
    "&authToken=security:AAA:BBB&isEnglishBook=false"
)

HTML_WITH_DOCS = """
<html><body>
<li class="courseware-wrapper">
  <div class="content-displayName" title="01 Introduction to Kunpeng">01 Introduction to Kunpeng</div>
  <div class="content-style"><iframe src="https://talent.shixizhi.huawei.com/edm3client/static/index.html?appid=APP&docId=DOC1&baseurl=https%3A%2F%2Fx%2F&authToken=t1"></iframe></div>
</li>
<li class="courseware-wrapper">
  <iframe src="https://talent.shixizhi.huawei.com/edm3client/static/index.html?appid=APP&docId=DOC1&baseurl=https%3A%2F%2Fx%2F&authToken=t1"></iframe>
</li>
<li class="courseware-wrapper">
  <iframe src="https://talent.shixizhi.huawei.com/edm3client/static/index.html?appid=APP&docId=DOC2&baseurl=https%3A%2F%2Fx%2F&authToken=t2"></iframe>
</li>
</body></html>
"""


def test_parse_edm_src_builds_preview_url() -> None:
    source = parse_edm_src(SRC)
    assert source.doc_id == "M1T9A107N954045138109755602"
    assert source.doc_version == "V1"
    assert source.token == "security:AAA:BBB"
    parsed = urlparse(source.preview_url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/edm/projects/881715bf5fd14684a8e95f6a904f869e/previewer/documents/M1T9A107N954045138109755602"
    assert query["docVersion"] == ["V1"]
    assert query["accessMode"] == ["client"]
    assert query["tableHeader"] == ["true"]


def test_parse_edm_src_rejects_non_edm() -> None:
    import pytest

    with pytest.raises(Exception):
        parse_edm_src("https://example.com/not-edm.html")


def test_decode_page_plain_png() -> None:
    content, kind = decode_page(b"\x89PNG fake", "1.png")
    assert kind == "image"
    assert content == b"\x89PNG fake"


def test_decode_page_pdf() -> None:
    content, kind = decode_page(b"%PDF-1.4 data", "page.pdf")
    assert kind == "pdf"
    assert content.startswith(b"%PDF")


def test_decode_page_gzipped_image() -> None:
    raw = b"\x89PNG gz-content"
    content, kind = decode_page(gzip.compress(raw), "1.png.gz")
    assert kind == "image"
    assert content == raw


def test_decode_page_gzipped_pdf() -> None:
    raw = b"%PDF-1.4 gz"
    content, kind = decode_page(gzip.compress(raw), "1.pdf.gz")
    assert kind == "pdf"
    assert content == raw


def test_filename_from_disposition() -> None:
    assert _filename_from_disposition("attachment;fileName=1.png") == "1.png"
    assert _filename_from_disposition('attachment; filename="2.pdf.gz"') == "2.pdf.gz"
    assert _filename_from_disposition(None) == ""


def test_collect_edm_sources_titles_and_dedupe() -> None:
    sources = collect_edm_sources(HTML_WITH_DOCS)
    assert len(sources) == 2
    assert sources[0][0] == "01 Introduction to Kunpeng"
    assert "DOC1" in sources[0][1]
    assert "DOC2" in sources[1][1]
