from __future__ import annotations

import html as html_module
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

HTML_TAG_RE = re.compile(
    r"<(?:p|div|span|img|h[1-6]|table|ul|ol|li|section|figure|br|strong|em)\b",
    re.IGNORECASE,
)

PRINT_CSS = """
@page { size: A4; margin: 16mm 14mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "Noto Serif", "DejaVu Serif", Georgia, "Songti SC", serif;
  font-size: 11pt; line-height: 1.6; color: #111; margin: 0;
}
h1, h2, h3, h4 { line-height: 1.3; page-break-after: avoid; }
img, svg, video, canvas { max-width: 100%; height: auto; }
table { border-collapse: collapse; width: 100%; page-break-inside: avoid; }
td, th { border: 1px solid #999; padding: 4px 6px; }
figure { margin: 1em 0; text-align: center; }
.chapter-header { border-bottom: 2px solid #333; margin-bottom: 1.2em; padding-bottom: .6em; }
.chapter-header .crumbs { font-size: 9pt; color: #555; margin-bottom: .3em; }
.chapter-header h1 { font-size: 18pt; margin: 0; }
.chapter-content { orphans: 3; widows: 3; }
.chapter-content img { page-break-inside: avoid; }
""".strip()


def slugify(value: str, fallback: str = "section") -> str:
    candidate = re.sub(r"[^\w\- ]+", "", value, flags=re.UNICODE).strip().lower()
    candidate = re.sub(r"[\s_]+", "-", candidate).strip("-")
    return candidate[:80] or fallback


def _looks_like_html(value: str) -> bool:
    return bool(HTML_TAG_RE.search(value))


def find_html_in_json(obj: Any) -> str | None:
    best = ""

    def walk(node: Any) -> None:
        nonlocal best
        if isinstance(node, str):
            if len(node) > len(best) and _looks_like_html(node):
                best = node
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(obj)
    return best or None


def extract_content_html(decrypted: str) -> str:
    stripped = decrypted.strip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            return decrypted
        found = find_html_in_json(parsed)
        if found is not None:
            return found
    return decrypted


def build_chapter_document(
    title: str,
    content_html: str,
    breadcrumb: list[str] | None = None,
    base_href: str | None = None,
) -> str:
    safe_title = html_module.escape(title or "Chapter")
    crumbs = " / ".join(html_module.escape(part) for part in (breadcrumb or []) if part)
    base_tag = f'<base href="{html_module.escape(base_href)}">' if base_href else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{safe_title}</title>{base_tag}"
        f"<style>{PRINT_CSS}</style></head><body>"
        '<header class="chapter-header">'
        f'<div class="crumbs">{crumbs}</div><h1>{safe_title}</h1>'
        "</header>"
        f'<main class="chapter-content">{content_html}</main>'
        "</body></html>"
    )


def html_to_text(content_html: str) -> str:
    soup = BeautifulSoup(content_html, "html.parser")
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def render_pdfs(items: list[tuple[Path, Path]], timeout: float = 120.0) -> None:
    if not items:
        return
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        for index, (html_path, pdf_path) in enumerate(items, start=1):
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle", timeout=timeout * 1000)
            page.emulate_media(media="print")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
            )
            print(f"  [pdf] {index}/{len(items)} {pdf_path.name}", flush=True)
        browser.close()


def merge_pdfs(items: list[tuple[Path, str]], out_path: Path, title: str) -> int:
    writer = PdfWriter()
    for pdf_path, chapter_title in items:
        if not pdf_path.exists():
            continue
        reader = PdfReader(str(pdf_path))
        start = len(writer.pages)
        for page in reader.pages:
            writer.add_page(page)
        writer.add_outline_item(chapter_title or pdf_path.stem, start)
    if len(writer.pages) == 0:
        return 0
    writer.add_metadata({"/Title": title, "/Creator": "hictc-web-scraper", "/Producer": "pypdf"})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        writer.write(handle)
    return len(writer.pages)
