from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .assets import collect_html_urls, download_resources, iter_resource_entries, rewrite_html_urls
from .capture import CaptureError, SessionResult, collect_session
from .client import EhepClient, EhepError
from .decrypt import DecryptError
from .edm import EdmError, collect_edm_sources, export_document, parse_edm_src
from .exporter import (
    build_chapter_document,
    extract_content_html,
    html_to_text,
    merge_pdfs,
    render_pdfs,
    slugify,
)
from .models import Auth, flatten_chapters

DEFAULT_FILE_TYPES = ("video", "audio", "image", "ct", "doc", "ppt", "pdf", "xr", "ilab")
TITLE_KEYS = ("title", "bookName", "name", "origName", "originalName")
DEFAULT_PAGE_ORIGIN = "https://talent.shixizhi.huawei.com"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hictc-web-scraper",
        description=(
            "Export a Huawei ICT course to text and PDF. Opens a browser for you to log in, "
            "captures the reader token, walks the course catalog and downloads/decrypts content."
        ),
    )
    parser.add_argument(
        "--url",
        help="course page URL, e.g. https://talent.shixizhi.huawei.com/course/<id>/course-learn",
    )
    parser.add_argument(
        "--from-html",
        metavar="FILE",
        help="offline mode: export every EDM document found in a saved course HTML file",
    )
    parser.add_argument(
        "-o",
        "--out",
        "--output-dir",
        dest="out",
        default="output",
        help="directory to dump all output into, created if missing (default: output)",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "course", "book"),
        default="auto",
        help=(
            "auto (default): walk the catalog AND export the digital textbook; "
            "course: only the catalog sections (graphic/text blocks); book: only the digital textbook"
        ),
    )
    parser.add_argument(
        "--profile",
        default=".browser-profile",
        help="playwright profile directory used to persist the login (default: .browser-profile)",
    )
    parser.add_argument("--headless", action="store_true", help="run the capture browser headless")
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="seconds to wait for you to open the course (default: 600)",
    )
    parser.add_argument(
        "--file-types",
        default=",".join(DEFAULT_FILE_TYPES),
        help="comma-separated resource file types to list (default: %(default)s)",
    )
    parser.add_argument("--skip-media", action="store_true", help="do not download media files")
    parser.add_argument("--skip-pdf", action="store_true", help="do not render the PDF output")
    parser.add_argument(
        "--max-media-mb",
        type=float,
        default=300.0,
        help="skip downloads larger than this size in MB (default: 300)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="delay in seconds between chapter/block requests (default: 0.15)",
    )
    parser.add_argument(
        "--edm-max-pages",
        type=int,
        default=0,
        help="maximum pages per EDM document, 0 for all (default: 0)",
    )
    parser.add_argument(
        "--edm-image-width",
        type=int,
        default=1600,
        help="downscale EDM page images to this pixel width in the PDF (default: 1600)",
    )
    return parser


def _first_string(obj: Any, keys: tuple[str, ...]) -> str:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = _first_string(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _first_string(value, keys)
            if found:
                return found
    return ""


def _try_json(path: Path, label: str, func: Any) -> Any:
    try:
        data = func()
    except EhepError as exc:
        print(f"[warn] {label} failed: {exc}")
        return None
    if data is not None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def export_book(auth: Auth, out_dir: Path, args: argparse.Namespace) -> bool:
    with EhepClient(auth) as client:
        book_info = _try_json(out_dir / "book-info.json", "book info", client.book_info)
        read_book = _try_json(out_dir / "read-book.json", "read book", client.read_book)
        tree = _try_json(out_dir / "chapter-tree.json", "chapter tree", client.chapter_tree)
        if tree is None:
            print("[error] could not fetch the chapter tree")
            return False

        chapters = flatten_chapters(tree)
        print(f"[book] found {len(chapters)} chapters/sections")

        resources: dict[str, Any] = {}
        for file_type in [item.strip() for item in args.file_types.split(",") if item.strip()]:
            try:
                data = client.resource_list(file_type)
            except EhepError as exc:
                print(f"[warn] resource list '{file_type}' failed: {exc}")
                continue
            if data:
                resources[file_type] = data
        if resources:
            (out_dir / "resources.json").write_text(
                json.dumps(resources, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        raw_dir = out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        for index, chapter in enumerate(chapters, start=1):
            label = " > ".join(part for part in chapter.breadcrumb if part) or chapter.title
            try:
                raw = client.chapter_content(chapter.id)
            except (EhepError, DecryptError) as exc:
                print(f"[warn] {index}/{len(chapters)} {label}: {exc}")
                continue
            name = f"{index:02d}-{slugify(chapter.title)}"
            (raw_dir / f"{name}.txt").write_text(raw, encoding="utf-8")
            content_html = extract_content_html(raw)
            records.append(
                {
                    "id": chapter.id,
                    "title": chapter.title,
                    "breadcrumb": chapter.breadcrumb,
                    "html": content_html,
                    "urls": sorted(collect_html_urls(content_html, auth.base_url)),
                    "name": name,
                }
            )
            print(f"  [book] {index}/{len(chapters)} {label}")
            if args.delay:
                time.sleep(args.delay)

    if not records:
        print("[error] no book chapter content was downloaded")
        return False

    url_map: dict[str, str] = {}
    if not args.skip_media:
        print("[book] downloading media resources...")
        entries = list(iter_resource_entries(resources))
        for record in records:
            for url in record["urls"]:
                entries.append((Path(url.split("?")[0]).name, url))
        url_map = download_resources(entries, out_dir, auth=auth, max_file_mb=args.max_media_mb)

    html_dir = out_dir / "html"
    text_dir = out_dir / "text"
    pdf_dir = out_dir / "pdf"
    html_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    pdf_items: list[tuple[Path, Path]] = []
    merge_items: list[tuple[Path, str]] = []
    for record in records:
        content = rewrite_html_urls(record["html"], url_map, auth.base_url)
        document = build_chapter_document(record["title"], content, record["breadcrumb"])
        html_path = html_dir / f"{record['name']}.html"
        html_path.write_text(document, encoding="utf-8")
        (text_dir / f"{record['name']}.txt").write_text(html_to_text(content), encoding="utf-8")
        if not args.skip_pdf:
            pdf_path = pdf_dir / f"{record['name']}.pdf"
            pdf_items.append((html_path, pdf_path))
            merge_items.append((pdf_path, record["title"]))

    if not args.skip_pdf:
        print("[book] rendering chapter PDFs...")
        render_pdfs(pdf_items)
        book_title = (
            _first_string(book_info, TITLE_KEYS) or _first_string(read_book, TITLE_KEYS) or "book"
        )
        merged_path = out_dir / f"{slugify(book_title, 'book')}.pdf"
        pages = merge_pdfs(merge_items, merged_path, book_title)
        if pages:
            print(f"[book] merged PDF: {merged_path} ({pages} pages)")

    book_summary = {
        "title": _first_string(book_info, TITLE_KEYS) or _first_string(read_book, TITLE_KEYS),
        "book": auth.params.get("book"),
        "base_url": auth.base_url,
        "chapters": [
            {"id": record["id"], "title": record["title"], "file": record["name"]}
            for record in records
        ],
        "media": url_map,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(book_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


def export_course(result: SessionResult, out_dir: Path, args: argparse.Namespace) -> bool:
    html_blocks = [block for block in result.blocks if block.kind == "html"]
    doc_blocks = [block for block in result.blocks if block.kind == "document"]
    block_records = [
        {
            "order": block.order,
            "node_id": block.node_id,
            "title": block.title,
            "kind": block.kind,
            "breadcrumb": block.breadcrumb,
            "urls": block.urls,
            "doc_src": block.doc_src,
            "html": block.html,
        }
        for block in result.blocks
    ]
    (out_dir / "course-blocks.json").write_text(
        json.dumps(
            {"title": result.course_title, "blocks": block_records},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not html_blocks and not doc_blocks:
        print("[course] no in-page sections were found")
        return False

    origin = result.page_origin or DEFAULT_PAGE_ORIGIN
    url_map: dict[str, str] = {}
    if not args.skip_media and html_blocks:
        print("[course] downloading media resources...")
        entries: list[tuple[str, str]] = []
        for block in html_blocks:
            for url in block.urls:
                resolved = urljoin(origin + "/", url)
                entries.append((Path(urlparse(resolved).path).name, resolved))
            for url in collect_html_urls(block.html, origin):
                entries.append((Path(urlparse(url).path).name, url))
        url_map = download_resources(
            entries,
            out_dir,
            cookies=result.cookies,
            max_file_mb=args.max_media_mb,
        )

    html_dir = out_dir / "course-html"
    text_dir = out_dir / "course-text"
    pdf_dir = out_dir / "course-pdf"
    html_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[tuple[int, Path, Path, str]] = []
    merge_entries: list[tuple[int, Path, str]] = []
    for block in html_blocks:
        title = block.title or (block.breadcrumb[-1] if block.breadcrumb else "") or f"Section {block.order}"
        name = f"{block.order:02d}-{slugify(title)}"
        content = rewrite_html_urls(block.html, url_map, origin)
        document = build_chapter_document(title, content, block.breadcrumb)
        html_path = html_dir / f"{name}.html"
        html_path.write_text(document, encoding="utf-8")
        (text_dir / f"{name}.txt").write_text(html_to_text(content), encoding="utf-8")
        if not args.skip_pdf:
            rendered.append((block.order, html_path, pdf_dir / f"{name}.pdf", title))

    if not args.skip_pdf and rendered:
        print("[course] rendering section PDFs...")
        render_pdfs([(html_path, pdf_path) for _, html_path, pdf_path, _ in rendered])
        for order, _, pdf_path, title in rendered:
            merge_entries.append((order, pdf_path, title))

    for block in doc_blocks:
        if args.skip_pdf:
            break
        title = block.title or (block.breadcrumb[-1] if block.breadcrumb else "") or f"Document {block.order}"
        name = f"{block.order:02d}-{slugify(title, 'document')}"
        try:
            doc_id = parse_edm_src(block.doc_src).doc_id
        except EdmError:
            doc_id = "?"
        print(f"[course] document '{title}' (docId={doc_id})")
        try:
            pages = export_document(
                block.doc_src,
                pdf_dir / f"{name}.pdf",
                image_width=args.edm_image_width,
                max_pages=args.edm_max_pages,
                delay=args.delay,
            )
        except EdmError as exc:
            print(f"[warn] document '{title}' failed: {exc}")
            continue
        if pages and not args.skip_pdf:
            print(f"  [course] {pages} pages")
            merge_entries.append((block.order, pdf_dir / f"{name}.pdf", title))

    if not args.skip_pdf and merge_entries:
        merge_entries.sort(key=lambda item: item[0])
        slug = slugify(result.course_title, "course")
        merged_path = out_dir / (f"{slug}-course.pdf" if slug != "course" else "course.pdf")
        total = merge_pdfs([(path, title) for _, path, title in merge_entries], merged_path, result.course_title or "Course")
        if total:
            print(f"[course] merged PDF: {merged_path} ({total} pages)")
    return True


def export_from_html(html_file: str, out_dir: Path, args: argparse.Namespace) -> bool:
    html_path = Path(html_file)
    if not html_path.is_file():
        print(f"[error] file not found: {html_file}", file=sys.stderr)
        return False
    raw = html_path.read_text(encoding="utf-8", errors="replace")
    sources = collect_edm_sources(raw)

    if not sources:
        print("[edm] no EDM documents found in the HTML file")
        return False

    edm_dir = out_dir / "edm"
    edm_dir.mkdir(parents=True, exist_ok=True)
    merge_items: list[tuple[Path, str]] = []
    for index, (title, src) in enumerate(sources, start=1):
        name = f"{index:02d}-{slugify(title, 'document')}"
        print(f"[edm] {index}/{len(sources)} {title}")
        try:
            pages = export_document(
                src,
                edm_dir / f"{name}.pdf",
                image_width=args.edm_image_width,
                max_pages=args.edm_max_pages,
                delay=args.delay,
            )
        except EdmError as exc:
            print(f"[warn] {title}: {exc}")
            continue
        if pages:
            print(f"  [edm] {pages} pages")
            merge_items.append((edm_dir / f"{name}.pdf", title))
    if not merge_items:
        print("[error] no EDM document could be exported", file=sys.stderr)
        return False
    merged = out_dir / "edm-documents.pdf"
    total = merge_pdfs(merge_items, merged, "EDM Documents")
    if total:
        print(f"[edm] merged PDF: {merged} ({total} pages)")
    return True


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.from_html:
        if not export_from_html(args.from_html, out_dir, args):
            return 1
        print(f"Done. Output written to {out_dir.resolve()}")
        return 0

    if not args.url:
        print("[error] --url is required (or use --from-html FILE)", file=sys.stderr)
        return 2

    want_book = args.mode in ("auto", "book")
    want_course = args.mode in ("auto", "course")

    result = collect_session(
        args.url,
        args.profile,
        headless=args.headless,
        timeout=args.timeout,
        want_book=want_book,
        want_course=want_course,
        walk_delay=args.delay,
    )

    ok = False
    if want_course:
        ok = export_course(result, out_dir, args) or ok
    if want_book:
        if result.auth is not None:
            ok = export_book(result.auth, out_dir, args) or ok
        elif args.mode == "book":
            print("[error] no digital textbook token was captured")
            return 1
    if not ok:
        print("[error] nothing was exported; check the messages above", file=sys.stderr)
        return 1
    print(f"Done. Output written to {out_dir.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except CaptureError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[error] interrupted", file=sys.stderr)
        return 130
