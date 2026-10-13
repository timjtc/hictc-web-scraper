from __future__ import annotations

from hictc_web_scraper.cli import build_parser


def test_out_default() -> None:
    args = build_parser().parse_args(["--url", "https://example.test"])
    assert args.out == "output"


def test_out_short_flag() -> None:
    args = build_parser().parse_args(["--url", "https://example.test", "-o", "/tmp/dump"])
    assert args.out == "/tmp/dump"


def test_output_dir_flag() -> None:
    args = build_parser().parse_args(["--url", "https://example.test", "--output-dir", "/tmp/dump2"])
    assert args.out == "/tmp/dump2"


def test_out_long_flag() -> None:
    args = build_parser().parse_args(["--url", "https://example.test", "--out", "dump3"])
    assert args.out == "dump3"


def test_mode_default() -> None:
    args = build_parser().parse_args(["--url", "https://example.test"])
    assert args.mode == "auto"


def test_mode_course() -> None:
    args = build_parser().parse_args(["--url", "https://example.test", "--mode", "course"])
    assert args.mode == "course"


def test_mode_book() -> None:
    args = build_parser().parse_args(["--url", "https://example.test", "--mode", "book"])
    assert args.mode == "book"
