from __future__ import annotations

from hictc_web_scraper.models import flatten_chapters

TREE = [
    {
        "_id": "ch1",
        "title": "Chapter 1 Introduction",
        "children": [
            {"_id": "ch1-1", "title": "1.1 Databases"},
            {"_id": "ch1-2", "title": "1.2 History"},
        ],
    },
    {"_id": "ch2", "title": "Chapter 2 openGauss", "children": []},
]


def test_flatten_order_and_ids() -> None:
    chapters = flatten_chapters(TREE)
    assert [chapter.id for chapter in chapters] == ["ch1", "ch1-1", "ch1-2", "ch2"]


def test_flatten_breadcrumbs_and_levels() -> None:
    chapters = flatten_chapters(TREE)
    child = chapters[1]
    assert child.breadcrumb == ["Chapter 1 Introduction", "1.1 Databases"]
    assert child.level == 1
    assert chapters[0].level == 0


def test_flatten_tolerates_missing_fields() -> None:
    chapters = flatten_chapters([{"chapterId": "x"}, {"title": "no id"}, "junk"])
    assert len(chapters) == 1
    assert chapters[0].id == "x"
    assert chapters[0].title == "Section 1"
