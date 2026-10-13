from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

MAX_WALK_ROUNDS = 8
MAX_WALK_NODES = 1500
_NOARG = object()

NODES_JS = """
() => {
  const selector = '.tree-node';
  return Array.from(document.querySelectorAll(selector)).map((node, index) => {
    const content = node.querySelector(':scope > .tree-node-content');
    const titleEl = content ? content.querySelector('p.text, p') : null;
    const title = titleEl ? ((titleEl.getAttribute('title') || titleEl.textContent || '').trim()) : '';
    const children = node.querySelector(':scope > .tree-node-children');
    const childCount = children ? children.querySelectorAll(':scope > .tree-node').length : 0;
    const breadcrumb = [];
    let el = node.parentElement;
    while (el) {
      if (el.classList && el.classList.contains('tree-node')) {
        const parentContent = el.querySelector(':scope > .tree-node-content');
        const parentTitle = parentContent ? parentContent.querySelector('p.text, p') : null;
        if (parentTitle) {
          breadcrumb.unshift((parentTitle.getAttribute('title') || parentTitle.textContent || '').trim());
        }
      }
      el = el.parentElement;
    }
    if (title) breadcrumb.push(title);
    return {
      id: node.id || '',
      index,
      title,
      isLeaf: childCount === 0,
      current: !!(content && content.classList.contains('is-current')),
      breadcrumb
    };
  });
}
"""

CLICK_JS = """
(payload) => {
  let node = payload.id ? document.getElementById(payload.id) : null;
  if (!node) {
    const all = document.querySelectorAll('.tree-node');
    node = all[payload.index];
  }
  if (!node) return false;
  const content = node.querySelector(':scope > .tree-node-content') || node.querySelector('.tree-node-content') || node;
  content.click();
  return true;
}
"""

SNAPSHOT_JS = """
() => {
  const main = document.querySelector('#innerContent') || document.querySelector('.learn-content-main') || document.body;
  const text = main ? (main.innerHTML || '') : '';
  let hash = 0;
  for (let i = 0; i < text.length; i += 5) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
  }
  const spinner = document.querySelector('.ant-spin-spinning, .kltCourse-spin-spinning, .el-loading-mask:not([style*="display: none"])');
  const reader = document.querySelector('iframe[src*="course-reader"]');
  return hash + ':' + text.length + ':' + (spinner ? 1 : 0) + ':' + (reader ? 1 : 0);
}
"""

EXTRACT_JS = """
() => {
  const main = document.querySelector('#innerContent') || document.querySelector('.learn-content-main') || document.body;
  if (!main) return { reader: false, document: false, docSrc: '', title: '', html: '', urls: [] };
  const titleEl = main.querySelector('.content-displayName') || main.querySelector('.display-name-text');
  const title = titleEl ? ((titleEl.getAttribute('title') || titleEl.textContent || '').trim()) : '';
  const readerFrame = document.querySelector('iframe[src*="course-reader"]');
  if (readerFrame) return { reader: true, document: false, docSrc: '', title, html: '', urls: [] };
  const edmFrame = document.querySelector('iframe[src*="edm3client"]');
  if (edmFrame) {
    return { reader: false, document: true, docSrc: edmFrame.getAttribute('src') || '', title, html: '', urls: [] };
  }
  const htmlEl = main.querySelector('.content-style-html');
  const urls = [];
  main.querySelectorAll('img[src], source[src], video[src], audio[src], a[href]').forEach((el) => {
    const value = el.getAttribute('src') || el.getAttribute('href');
    if (value && value.indexOf('data:') !== 0) urls.push(value);
  });
  return {
    reader: false,
    document: false,
    docSrc: '',
    title,
    html: htmlEl ? htmlEl.innerHTML : '',
    urls
  };
}
"""


@dataclass
class CourseBlock:
    order: int = 0
    title: str = ""
    kind: str = "html"
    html: str = ""
    urls: list[str] = field(default_factory=list)
    breadcrumb: list[str] = field(default_factory=list)
    node_id: str = ""
    doc_src: str = ""

    @property
    def content_hash(self) -> str:
        return hashlib.sha1(self.html.encode("utf-8")).hexdigest()


def finalize_blocks(blocks: list[CourseBlock]) -> list[CourseBlock]:
    result: list[CourseBlock] = []
    seen_html: set[str] = set()
    seen_docs: set[str] = set()
    for block in blocks:
        if block.kind == "reader":
            result.append(block)
            continue
        if block.kind == "document":
            if not block.doc_src or block.doc_src in seen_docs:
                continue
            seen_docs.add(block.doc_src)
            result.append(block)
            continue
        if not block.html.strip():
            continue
        digest = block.content_hash
        if digest in seen_html:
            continue
        seen_html.add(digest)
        result.append(block)
    for position, block in enumerate(result, start=1):
        block.order = position
    return result


def _node_key(node: dict[str, Any]) -> str:
    seed = "|".join(
        [str(node.get("title") or ""), *[str(part) for part in node.get("breadcrumb") or []]]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _page_closed(page: Page) -> bool:
    try:
        return page.is_closed()
    except PlaywrightError:
        return True


def _evaluate(page: Page, script: str, arg: Any = _NOARG) -> Any:
    try:
        if arg is _NOARG:
            return page.evaluate(script)
        return page.evaluate(script, arg)
    except PlaywrightError:
        return None


def walk_course(
    page: Page,
    delay: float = 0.15,
    leaf_settle: float = 3.0,
    parent_settle: float = 1.2,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[CourseBlock]:
    blocks: list[CourseBlock] = []
    visited: set[str] = set()
    seen_content: set[str] = set()
    seen_special: set[str] = set()
    previous = _evaluate(page, SNAPSHOT_JS)
    processed = 0
    total_hint = 0

    for round_number in range(1, MAX_WALK_ROUNDS + 1):
        if _page_closed(page):
            print("[warn] course page was closed; stopping the walk")
            break
        nodes: list[dict[str, Any]] = _evaluate(page, NODES_JS) or []
        total_hint = max(total_hint, len(nodes))
        pending = [node for node in nodes if _node_key(node) not in visited]
        if not pending:
            break
        if round_number > 1:
            print(f"[course] catalog changed, re-scanning ({len(pending)} new item(s))", flush=True)
        new_in_round = 0

        for node in pending:
            if _page_closed(page):
                print("[warn] course page was closed; stopping the walk")
                break
            if len(visited) >= MAX_WALK_NODES:
                print(f"[warn] stopping after {MAX_WALK_NODES} catalog items")
                break
            key = _node_key(node)
            visited.add(key)
            settle = leaf_settle if node.get("isLeaf") else parent_settle
            if not node.get("current"):
                clicked = _evaluate(
                    page, CLICK_JS, {"id": node.get("id", ""), "index": node.get("index", 0)}
                )
                if clicked is None:
                    break
                if not clicked:
                    continue
                deadline = time.monotonic() + settle
                while time.monotonic() < deadline:
                    time.sleep(0.1)
                    snapshot = _evaluate(page, SNAPSHOT_JS)
                    if snapshot is None:
                        break
                    if snapshot != previous:
                        time.sleep(min(delay, 0.4))
                        break
                previous = _evaluate(page, SNAPSHOT_JS)

            data = _evaluate(page, EXTRACT_JS)
            if data is None:
                break
            title = (data.get("title") or node.get("title") or "").strip()
            processed += 1
            if on_progress is not None:
                on_progress(processed, total_hint, title)
            if data.get("reader"):
                if key in seen_special:
                    continue
                seen_special.add(key)
                blocks.append(
                    CourseBlock(
                        title=title,
                        kind="reader",
                        breadcrumb=list(node.get("breadcrumb") or []),
                        node_id=node.get("id", ""),
                    )
                )
                new_in_round += 1
            elif data.get("document"):
                if key in seen_special:
                    continue
                seen_special.add(key)
                blocks.append(
                    CourseBlock(
                        title=title,
                        kind="document",
                        doc_src=data.get("docSrc") or "",
                        breadcrumb=list(node.get("breadcrumb") or []),
                        node_id=node.get("id", ""),
                    )
                )
                new_in_round += 1
            else:
                html = data.get("html") or ""
                if not html.strip():
                    continue
                digest = hashlib.sha1(html.encode("utf-8")).hexdigest()
                if digest in seen_content:
                    continue
                seen_content.add(digest)
                blocks.append(
                    CourseBlock(
                        title=title,
                        kind="html",
                        html=html,
                        urls=list(data.get("urls") or []),
                        breadcrumb=list(node.get("breadcrumb") or []),
                        node_id=node.get("id", ""),
                    )
                )
                new_in_round += 1
            if delay:
                time.sleep(delay)

        if _page_closed(page):
            break
        if new_in_round == 0:
            break

    return finalize_blocks(blocks)
