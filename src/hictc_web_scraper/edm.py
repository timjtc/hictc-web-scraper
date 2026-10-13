from __future__ import annotations

import gzip
import json
import re
import time
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader, PdfWriter


class EdmError(RuntimeError):
    pass


class EdmTranscodingError(EdmError):
    pass


@dataclass
class EdmSource:
    preview_url: str
    doc_id: str
    doc_version: str
    doc_format: str
    token: str
    user_id: str = ""
    referer: str = "https://talent.shixizhi.huawei.com/"
    total_page: int = 0
    orig_ext: str = ""

    @property
    def page_count(self) -> int:
        return self.total_page


def parse_edm_src(src: str) -> EdmSource:
    parsed = urlparse(src)
    query = {key: value[0] for key, value in parse_qs(parsed.query).items()}
    if "edm3client" not in parsed.path:
        raise EdmError(f"not an EDM iframe URL: {src[:120]}")
    baseurl = query.get("baseurl") or f"{parsed.scheme}://{parsed.netloc}/"
    appid = query.get("appid") or ""
    doc_id = query.get("docId") or ""
    if not appid or not doc_id:
        raise EdmError("EDM iframe URL is missing appid or docId")
    doc_version = query.get("docVersion") or ""
    doc_format = query.get("docFormat") or ""
    user_id = query.get("userId") or ""
    token = query.get("authToken") or ""
    extra = {
        "docVersion": doc_version,
        "wmType": query.get("wmType", ""),
        "renderDocType": "",
        "accessMode": "client",
        "docFormat": doc_format,
        "userId": user_id,
        "X-IAM-ACCOUNT": query.get("xIamAccount", ""),
        "X-HIC-Info": query.get("xHicInfo", ""),
        "tableHeader": "true",
    }
    preview_url = f"{baseurl}edm/projects/{appid}/previewer/documents/{doc_id}?" + urlencode(extra)
    return EdmSource(
        preview_url=preview_url,
        doc_id=doc_id,
        doc_version=doc_version,
        doc_format=doc_format,
        token=token,
        user_id=user_id,
        referer=query.get("PMurl") or query.get("openerOrigin") or "https://talent.shixizhi.huawei.com/",
    )


def collect_edm_sources(raw_html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(raw_html, "html.parser")
    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    for frame in soup.select('iframe[src*="edm3client"]'):
        src = (frame.get("src") or "").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        title = ""
        container = frame.find_parent("li") or frame.parent
        if container is not None:
            element = container.select_one(".content-displayName, .display-name-text, p.text")
            if element is not None:
                title = (element.get("title") or element.get_text() or "").strip()
        if not title:
            try:
                title = parse_edm_src(src).doc_id
            except EdmError:
                title = f"document-{len(sources) + 1}"
        sources.append((title, src))
    return sources


def _filename_from_disposition(header: str | None) -> str:
    if not header:
        return ""
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.IGNORECASE)
    return match.group(1) if match else ""


def decode_page(content: bytes, filename: str) -> tuple[bytes, str]:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix == "gz":
        try:
            inflated = gzip.decompress(content)
        except OSError:
            inflated = zlib.decompress(content)
        inner = Path(filename[: -len(".gz")]).suffix.lower().lstrip(".")
        suffix = inner or "bin"
        content = inflated
    if suffix == "pdf":
        return content, "pdf"
    if suffix in ("svg", "xml"):
        return content, "svg"
    return content, "image"


class EdmClient:
    def __init__(self, source: EdmSource, timeout: float = 60.0) -> None:
        self.source = source
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "EDM-Authorization": source.token,
                "Referer": source.referer,
                "Accept": "application/json, */*",
                "User-Agent": "Mozilla/5.0",
            }
        )

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "EdmClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def info(self) -> dict[str, Any]:
        response = self.session.get(self.source.preview_url, timeout=self.timeout)
        if response.status_code in (401, 403):
            raise EdmError(f"document access denied (HTTP {response.status_code}); token may have expired")
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise EdmError(f"unexpected EDM response: {response.text[:200]}") from exc
        http_code = data.get("httpCode")
        if http_code in (401, 403):
            raise EdmError(f"document access denied (code {http_code}); token may have expired")
        if data.get("errorCode") == 12014:
            raise EdmError("document does not exist")
        convert_result = data.get("convertResult")
        if convert_result not in (1, None):
            raise EdmError(f"document conversion result: {convert_result}")
        self.source.total_page = int(data.get("totalPage") or 0)
        self.source.orig_ext = str(data.get("origFileExtension") or "")
        if data.get("docFormat"):
            self.source.doc_format = str(data["docFormat"])
        return data

    def page(self, page_num: int, document_index: int = 1) -> tuple[bytes, str]:
        body = {
            "docFormat": self.source.doc_format or "src",
            "docId": self.source.doc_id,
            "docVersion": self.source.doc_version,
            "documentIndex": document_index,
            "pageNum": page_num,
            "type": "doc",
            "totalPage": self.source.total_page,
            "userId": self.source.user_id,
        }
        response = self.session.post(
            self.source.preview_url, data=json.dumps(body), timeout=self.timeout
        )
        if response.status_code in (401, 403):
            raise EdmError(f"page access denied (HTTP {response.status_code})")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if payload.get("status") == 19000:
                raise EdmTranscodingError("document is still being transcoded")
            raise EdmError(f"page {page_num} failed: {payload.get('errorMsg') or payload.get('message') or content_type}")
        filename = _filename_from_disposition(response.headers.get("content-disposition"))
        return decode_page(response.content, filename)


def _image_page_pdf(data: bytes, image_width: int) -> bytes:
    image = Image.open(BytesIO(data))
    if image.mode != "RGB":
        image = image.convert("RGB")
    if image_width and image.width > image_width:
        ratio = image_width / float(image.width)
        image = image.resize((image_width, max(1, int(image.height * ratio))), Image.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="PDF")
    image.close()
    return buffer.getvalue()


def build_pdf(pages: list[tuple[bytes, str]], out_path: Path, image_width: int = 1600) -> int:
    writer = PdfWriter()
    for data, kind in pages:
        if kind == "pdf":
            reader = PdfReader(BytesIO(data))
            for page in reader.pages:
                writer.add_page(page)
        elif kind == "image":
            reader = PdfReader(BytesIO(_image_page_pdf(data, image_width)))
            writer.add_page(reader.pages[0])
    if len(writer.pages) == 0:
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        writer.write(handle)
    return len(writer.pages)


def export_document(
    src: str,
    out_path: Path,
    image_width: int = 1600,
    max_pages: int = 0,
    delay: float = 0.1,
    timeout: float = 60.0,
    retries: int = 3,
) -> int:
    source = parse_edm_src(src)
    with EdmClient(source, timeout=timeout) as client:
        client.info()
        total = source.page_count
        limit = total if max_pages <= 0 else min(total, max_pages)
        pages: list[tuple[bytes, str]] = []
        for page_num in range(1, limit + 1):
            for attempt in range(retries + 1):
                try:
                    pages.append(client.page(page_num))
                    break
                except EdmTranscodingError:
                    if attempt >= retries:
                        raise
                    time.sleep(3.0)
            if delay:
                time.sleep(delay)
    return build_pdf(pages, out_path, image_width=image_width)
