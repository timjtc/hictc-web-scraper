from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from playwright.sync_api import Page, Response, sync_playwright

from .course import CourseBlock, walk_course
from .models import Auth

ALLOWED_HEADER_KEYS = {
    "x-plugin-token",
    "id-token",
    "user-agent",
    "origin",
    "referer",
    "accept",
    "accept-language",
    "cookie",
    "x-requested-with",
}

SKIP_PARAM_KEYS = {
    "id",
    "chapter",
    "chapterId",
    "fileType",
    "keyword",
    "limit",
    "showChapterPath",
    "env",
}

PLUGIN_API_MARKER = "/eapi/v2/plugin/"
DEFAULT_EHEP_BASE = "https://ehep.com.cn"
DEFAULT_TALENT_ORIGIN = "https://talent.shixizhi.huawei.com"

MESSAGE_HOOK = """
(() => {
  if (window.__hictcInit) return;
  window.__hictcInit = true;
  window.__hictcMessages = [];
  window.addEventListener('message', (event) => {
    try {
      const data = event && event.data;
      if (data && typeof data === 'object' && typeof data.type === 'string') {
        window.__hictcMessages.push({ type: data.type, data: data.data || {}, origin: event.origin || '' });
      }
    } catch (err) {}
  }, true);
})();
"""


class CaptureError(RuntimeError):
    pass


class CaptureTimeout(CaptureError):
    pass


def extract_change_block(messages: Any) -> dict[str, Any] | None:
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("type") != "changeBlock":
            continue
        data = message.get("data")
        if not isinstance(data, dict):
            continue
        book_id = data.get("bookId")
        if not (isinstance(book_id, str) and book_id):
            continue
        reader_token = data.get("readerToken")
        return {
            "book_id": book_id,
            "reader_token": reader_token if isinstance(reader_token, str) else "",
            "is_english": bool(data.get("isEnglishBook")),
        }
    return None


def auth_from_change_block(block: dict[str, Any], id_token: str | None = None) -> Auth:
    headers = {
        "x-plugin-token": block["reader_token"],
        "accept": "application/json",
        "origin": DEFAULT_TALENT_ORIGIN,
        "referer": DEFAULT_TALENT_ORIGIN + "/",
        "user-agent": "Mozilla/5.0",
    }
    return Auth(
        base_url=DEFAULT_EHEP_BASE,
        plugin_token=block["reader_token"],
        id_token=id_token,
        params={"book": block["book_id"]},
        headers=headers,
    )


def _extract_auth(response: Response) -> Auth | None:
    request = response.request
    parsed = urlparse(request.url)
    if "ehep.com.cn" not in parsed.netloc:
        return None
    if PLUGIN_API_MARKER not in parsed.path:
        return None

    try:
        raw_headers = request.all_headers()
    except Exception:
        raw_headers = request.headers
    headers = {key.lower(): value for key, value in raw_headers.items()}
    plugin_token = headers.get("x-plugin-token")
    if not plugin_token:
        return None

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params = {key: value for key, value in query.items() if key not in SKIP_PARAM_KEYS}
    if "book" not in params:
        return None

    safe_headers = {key: value for key, value in headers.items() if key in ALLOWED_HEADER_KEYS}
    safe_headers["accept"] = "application/json"

    return Auth(
        base_url=f"{parsed.scheme}://{parsed.netloc}",
        plugin_token=plugin_token,
        id_token=headers.get("id-token"),
        params=params,
        headers=safe_headers,
    )


def _cookie_value(cookies: list[dict[str, Any]], name: str) -> str | None:
    for cookie in cookies:
        if cookie.get("name") == name and cookie.get("value"):
            return str(cookie["value"])
    return None


def _scan_messages(context: Any) -> dict[str, Any] | None:
    for page in context.pages:
        try:
            frames = page.frames
        except Exception:
            continue
        for frame in frames:
            try:
                messages = frame.evaluate("() => window.__hictcMessages || []")
            except Exception:
                continue
            block = extract_change_block(messages)
            if block is not None and block.get("reader_token"):
                return block
    return None


def _describe(context: Any) -> str:
    parts = []
    for page in context.pages:
        try:
            parts.append(f"{urlparse(page.url).netloc}{urlparse(page.url).path[:40]}")
        except Exception:
            continue
    return f"pages={len(context.pages)} [{', '.join(parts)}]"


@dataclass
class SessionResult:
    auth: Auth | None
    blocks: list[CourseBlock]
    page_origin: str
    cookies: list[dict[str, Any]]
    catalog_found: bool
    course_title: str = ""


def _find_catalog_page(context: Any) -> Page | None:
    for page in context.pages:
        try:
            if page.query_selector(".tree-node-content"):
                return page
        except Exception:
            continue
    return None


def collect_session(
    url: str,
    profile_dir: str | Path,
    headless: bool = False,
    timeout: float = 600.0,
    poll_interval: float = 1.0,
    want_book: bool = True,
    want_course: bool = False,
    walk_delay: float = 0.15,
) -> SessionResult:
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    found: dict[str, Auth] = {}
    auth_found_at: dict[str, float] = {}
    blocks: list[CourseBlock] = []
    catalog_holder: dict[str, Page] = {}
    page_origin = ""
    course_title = ""

    def handle_response(response: Response) -> None:
        if "auth" in found:
            return
        try:
            auth = _extract_auth(response)
        except Exception:
            return
        if auth is not None:
            found["auth"] = auth
            auth_found_at["ts"] = time.monotonic()
            print(f"[capture] reader token detected via network ({auth.params.get('book')})", flush=True)

    print(
        "\n"
        "A browser window was opened with your saved profile.\n"
        "IMPORTANT: do everything in that window, not in your regular browser.\n"
        "1. Log in to Huawei Talent if prompted.\n"
        + (
            "2. Open the course so its chapter catalog is visible.\n"
            "3. The script will walk the catalog and extract every section automatically.\n"
            if want_course
            else "2. Open the course and click the digital textbook entry in the catalog.\n"
            "   The book reader must start for the token to be captured.\n"
        )
        + "   Status updates appear below every 15 seconds.\n",
        flush=True,
    )

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context.add_init_script(script=MESSAGE_HOOK)
        context.on("response", handle_response)

        page: Page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        except Exception as exc:
            context.close()
            raise CaptureError(f"failed to open {url}: {exc}") from exc

        deadline = time.monotonic() + timeout
        last_status = 0.0
        try:
            while True:
                if not context.pages:
                    raise CaptureError("browser window was closed before the session was ready")
                if "auth" not in found:
                    block = _scan_messages(context)
                    if block is not None:
                        id_token = None
                        try:
                            id_token = _cookie_value(context.cookies(), "id-token")
                        except Exception:
                            pass
                        found["auth"] = auth_from_change_block(block, id_token)
                        auth_found_at["ts"] = time.monotonic()
                        print(
                            f"[capture] reader token detected via page handshake "
                            f"(book={block['book_id']})",
                            flush=True,
                        )
                if want_course and "page" not in catalog_holder:
                    catalog = _find_catalog_page(context)
                    if catalog is not None:
                        catalog_holder["page"] = catalog
                        print("[course] catalog detected, ready to walk", flush=True)
                ready = True
                if want_course and "page" not in catalog_holder:
                    catalog_grace = 0.0
                    if want_book and "auth" in found:
                        catalog_grace = time.monotonic() - auth_found_at["ts"]
                    if catalog_grace < 30.0:
                        ready = False
                if want_book and not want_course and "auth" not in found:
                    ready = False
                if ready:
                    break
                now = time.monotonic()
                if now > deadline:
                    break
                if now - last_status >= 15.0:
                    last_status = now
                    remaining = max(0.0, deadline - now)
                    target = (
                        "open the course page with its catalog"
                        if want_course and "page" not in catalog_holder
                        else "waiting for the digital textbook to open"
                    )
                    print(
                        f"[status] {remaining:.0f}s left - {_describe(context)} - {target}",
                        flush=True,
                    )
                time.sleep(poll_interval)

            catalog_page = catalog_holder.get("page")
            if want_course and catalog_page is not None:
                try:
                    page_origin = "{0.scheme}://{0.netloc}".format(urlparse(catalog_page.url))
                    course_title = catalog_page.title()
                except Exception:
                    page_origin = ""
                    course_title = ""
                print("[course] walking catalog, this can take a few minutes...", flush=True)

                def progress(done: int, total: int, title: str) -> None:
                    if done % 10 == 0 or done == total:
                        print(f"  [course] {done}/{total} {title[:70]}", flush=True)

                blocks = walk_course(catalog_page, delay=walk_delay, on_progress=progress)
                non_reader = sum(1 for block in blocks if block.kind == "html")
                print(f"[course] extracted {non_reader} content sections", flush=True)

                if "auth" not in found:
                    block = _scan_messages(context)
                    if block is not None:
                        id_token = _cookie_value(context.cookies(), "id-token")
                        found["auth"] = auth_from_change_block(block, id_token)
                        auth_found_at["ts"] = time.monotonic()
                        print(
                            f"[capture] reader token detected via page handshake "
                            f"(book={block['book_id']})",
                            flush=True,
                        )

            if want_book and not want_course and "auth" not in found:
                raise CaptureTimeout(
                    f"no course reader activity captured within {timeout:.0f}s; "
                    "make sure a chapter of the digital textbook is actually open"
                )

            cookies: list[dict[str, Any]] = []
            try:
                cookies = context.cookies()
            except Exception:
                cookies = []
        finally:
            context.close()

    auth = found.get("auth")
    if auth is not None:
        print(
            f"[capture] ready: book={auth.params.get('book')} base={auth.base_url} "
            f"id_token={'yes' if auth.id_token else 'no'}",
            flush=True,
        )
    return SessionResult(
        auth=auth,
        blocks=blocks,
        page_origin=page_origin,
        cookies=cookies,
        catalog_found="page" in catalog_holder,
        course_title=course_title,
    )


def capture_auth(
    url: str,
    profile_dir: str | Path,
    headless: bool = False,
    timeout: float = 600.0,
    poll_interval: float = 1.0,
) -> Auth:
    result = collect_session(
        url,
        profile_dir,
        headless=headless,
        timeout=timeout,
        poll_interval=poll_interval,
        want_book=True,
        want_course=False,
    )
    if result.auth is None:
        raise CaptureTimeout(
            f"no course reader activity captured within {timeout:.0f}s; "
            "make sure a chapter of the digital textbook is actually open"
        )
    return result.auth
