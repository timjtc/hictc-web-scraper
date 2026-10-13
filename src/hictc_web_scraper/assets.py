from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import Auth

URL_ATTRIBUTES = (
    "src",
    "href",
    "data-src",
    "data-original",
    "data-url",
    "poster",
)

NAME_KEYS = ("origName", "originalName", "filename", "fileName", "name", "title")
URL_KEYS = (
    "url",
    "fileUrl",
    "fileURL",
    "resourceUrl",
    "downloadUrl",
    "previewUrl",
    "ossUrl",
    "src",
    "link",
    "path",
    "filePath",
)

MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico",
    ".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv",
    ".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip",
}


def _is_url(value: str) -> bool:
    if value.startswith(("http://", "https://", "//")):
        return True
    if value.startswith("/") and Path(urlparse(value).path).suffix.lower() in MEDIA_EXTENSIONS:
        return True
    return False


def iter_resource_entries(data: Any) -> Iterator[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = ""
            for key in NAME_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    name = value.strip()
                    break
            for key in URL_KEYS:
                value = node.get(key)
                if isinstance(value, str) and _is_url(value) and value not in seen:
                    seen.add(value)
                    entries.append((name, value))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    yield from entries


def collect_html_urls(html: str, base_url: str) -> set[str]:
    urls: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        for attr in URL_ATTRIBUTES:
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                urls.add(urljoin(base_url + "/", value.strip()))
        srcset = tag.get("srcset")
        if isinstance(srcset, str):
            for part in srcset.split(","):
                candidate = part.strip().split(" ")[0]
                if candidate:
                    urls.add(urljoin(base_url + "/", candidate))
    return urls


def _safe_name(name: str, fallback: str) -> str:
    candidate = unquote(name).strip().replace("\\", "/").rsplit("/", 1)[-1]
    candidate = re.sub(r"[^\w.\- ]+", "_", candidate, flags=re.UNICODE).strip(" ._")
    if not candidate:
        candidate = fallback
    if len(candidate) > 120:
        stem, dot, suffix = candidate.rpartition(".")
        candidate = (stem[:100] + dot + suffix) if dot else candidate[:120]
    return candidate


def cookies_for_url(url: str, cookies: list[dict[str, Any]] | None) -> str:
    if not cookies:
        return ""
    host = urlparse(url).hostname or ""
    jar: list[str] = []
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        domain = str(cookie.get("domain") or "").lstrip(".")
        if domain and (host == domain or host.endswith("." + domain)):
            jar.append(f"{name}={value}")
    return "; ".join(jar)


def download_resources(
    entries: list[tuple[str, str]],
    out_dir: Path,
    auth: Auth | None = None,
    cookies: list[dict[str, Any]] | None = None,
    max_file_mb: float = 300.0,
    timeout: float = 60.0,
) -> dict[str, str]:
    media_dir = out_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["user-agent"] = (auth.headers.get("user-agent") if auth else None) or "Mozilla/5.0"
    if auth is not None:
        session.headers["referer"] = auth.base_url + "/"
    else:
        session.headers["referer"] = "https://talent.shixizhi.huawei.com/"

    mapping: dict[str, str] = {}
    used_names: set[str] = set()
    max_bytes = int(max_file_mb * 1024 * 1024)

    unique: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for name, url in entries:
        if url not in seen_urls:
            seen_urls.add(url)
            unique.append((name, url))

    for index, (name, url) in enumerate(unique, start=1):
        if url.startswith("//"):
            saved_url = "https:" + url
        elif url.startswith("/") and auth is not None:
            saved_url = auth.base_url + url
        else:
            saved_url = url
        if not saved_url.startswith(("http://", "https://")):
            continue
        filename = _safe_name(name, f"asset_{index:04d}")
        if "." not in filename:
            suffix = Path(urlparse(saved_url).path).suffix
            if suffix:
                filename += suffix
        stem, dot, suffix = filename.rpartition(".")
        candidate = filename
        counter = 1
        while candidate.lower() in used_names:
            counter += 1
            candidate = f"{stem}_{counter}{dot}{suffix}" if dot else f"{filename}_{counter}"
        used_names.add(candidate.lower())
        target = media_dir / candidate

        request_headers: dict[str, str] = {}
        cookie_header = cookies_for_url(saved_url, cookies)
        if cookie_header:
            request_headers["cookie"] = cookie_header
        try:
            with session.get(saved_url, stream=True, timeout=timeout, headers=request_headers) as response:
                if response.status_code >= 400:
                    print(f"  [media] skip {saved_url} (HTTP {response.status_code})")
                    continue
                content_type = response.headers.get("content-type", "")
                if content_type and not (
                    content_type.startswith(("image/", "video/", "audio/", "application/"))
                    or "octet-stream" in content_type
                ):
                    print(f"  [media] skip {saved_url} (content-type {content_type})")
                    continue
                written = 0
                with target.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError(f"file exceeds {max_file_mb:.0f} MB")
                        handle.write(chunk)
            if written == 0:
                target.unlink(missing_ok=True)
                continue
            mapping[saved_url] = posixpath.join("media", candidate)
            mapping[url] = posixpath.join("media", candidate)
            print(f"  [media] saved {candidate} ({written / 1024:.0f} KiB)")
        except Exception as exc:
            target.unlink(missing_ok=True)
            print(f"  [media] failed {saved_url}: {exc}")

    if mapping:
        (out_dir / "media-index.json").write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return mapping


def rewrite_html_urls(html: str, url_map: dict[str, str], base_url: str, html_dirname: str = "html") -> str:
    if not url_map:
        return html
    by_absolute: dict[str, str] = {}
    for url, relative in url_map.items():
        by_absolute[url] = relative
        by_absolute[urljoin(base_url + "/", url)] = relative

    soup = BeautifulSoup(html, "html.parser")
    changed = False

    def resolve(value: str) -> str | None:
        absolute = urljoin(base_url + "/", value.strip())
        relative = by_absolute.get(absolute) or by_absolute.get(value.strip())
        if relative is None:
            return None
        return posixpath.relpath(relative, html_dirname)

    for tag in soup.find_all(True):
        for attr in URL_ATTRIBUTES:
            value = tag.get(attr)
            if not isinstance(value, str) or not value.strip():
                continue
            replacement = resolve(value)
            if replacement:
                tag[attr] = replacement
                changed = True
        srcset = tag.get("srcset")
        if isinstance(srcset, str):
            parts = []
            for part in srcset.split(","):
                tokens = part.strip().split(" ")
                if tokens:
                    replacement = resolve(tokens[0])
                    if replacement:
                        tokens[0] = replacement
                        changed = True
                parts.append(" ".join(tokens))
            if changed:
                tag["srcset"] = ", ".join(parts)

    return str(soup) if changed else html
