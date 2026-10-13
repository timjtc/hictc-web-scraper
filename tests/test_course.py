from __future__ import annotations

from hictc_web_scraper.course import CourseBlock, finalize_blocks


def test_finalize_dedupes_identical_html() -> None:
    blocks = [
        CourseBlock(title="A", html="<p>x</p>"),
        CourseBlock(title="A duplicate", html="<p>x</p>"),
        CourseBlock(title="B", html="<p>y</p>"),
        CourseBlock(title="Reader", kind="reader"),
    ]
    result = finalize_blocks(blocks)
    assert [block.title for block in result] == ["A", "B", "Reader"]
    assert [block.order for block in result] == [1, 2, 3]


def test_finalize_skips_empty_html() -> None:
    assert finalize_blocks([CourseBlock(title="empty", html="   ")]) == []


def test_finalize_keeps_reader_blocks() -> None:
    result = finalize_blocks([CourseBlock(title="Book", kind="reader")])
    assert len(result) == 1
    assert result[0].kind == "reader"


def test_finalize_keeps_documents_and_dedupes() -> None:
    blocks = [
        CourseBlock(title="Doc 1", kind="document", doc_src="https://x/edm3client?docId=1"),
        CourseBlock(title="Doc 1 again", kind="document", doc_src="https://x/edm3client?docId=1"),
        CourseBlock(title="Empty doc", kind="document", doc_src=""),
    ]
    result = finalize_blocks(blocks)
    assert len(result) == 1
    assert result[0].title == "Doc 1"
    assert result[0].order == 1


def test_content_hash_stable() -> None:
    first = CourseBlock(html="<p>same</p>")
    second = CourseBlock(html="<p>same</p>")
    assert first.content_hash == second.content_hash
