from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .decrypt import decrypt_payload
from .models import Auth

CHAPTER_TREE_PATH = "/eapi/v2/plugin/chapter/tree"
CHAPTER_CONTENT_PATH = "/eapi/v2/plugin/chapter/centent/encrypt/v2"
BOOK_INFO_PATH = "/eapi/v2/plugin/book/info"
READ_BOOK_PATH = "/eapi/v2/plugin/read/book"
RESOURCE_LIST_PATH = "/eapi/v2/plugin/book/resource/list"


class EhepError(RuntimeError):
    pass


class EhepClient:
    def __init__(self, auth: Auth, timeout: float = 30.0, retries: int = 3) -> None:
        self.auth = auth
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=retries,
            backoff_factor=0.7,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(auth.headers)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "EhepClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        merged: dict[str, Any] = dict(self.auth.params)
        if params:
            merged.update(params)
        response = self.session.get(self.auth.base_url + path, params=merged, timeout=self.timeout)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise EhepError(f"{path}: response is not JSON: {response.text[:200]}") from exc
        if isinstance(body, dict) and body.get("success") is False:
            raise EhepError(f"{path}: code={body.get('code')} message={body.get('message')}")
        return body

    def book_info(self) -> Any:
        return self._get(BOOK_INFO_PATH).get("data")

    def read_book(self) -> Any:
        return self._get(READ_BOOK_PATH).get("data")

    def chapter_tree(self) -> Any:
        return self._get(CHAPTER_TREE_PATH).get("data")

    def chapter_content(self, chapter_id: str) -> str:
        body = self._get(CHAPTER_CONTENT_PATH, {"id": chapter_id})
        return decrypt_payload(body)

    def resource_list(self, file_type: str | None = None, limit: int = 9999) -> Any:
        params: dict[str, Any] = {"limit": limit, "showChapterPath": "true"}
        if file_type:
            params["fileType"] = file_type
        return self._get(RESOURCE_LIST_PATH, params).get("data")
