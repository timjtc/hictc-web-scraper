from __future__ import annotations

from typing import Any

from hictc_web_scraper.capture import (
    _extract_auth,
    auth_from_change_block,
    extract_change_block,
)


class FakeRequest:
    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.url = url
        self._headers = headers

    def all_headers(self) -> dict[str, str]:
        return self._headers


class FakeResponse:
    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.request = FakeRequest(url, headers)


BASE = "https://ehep.com.cn/eapi/v2/plugin/chapter/centent/encrypt/v2"


def test_extract_auth_basic() -> None:
    response = FakeResponse(
        f"{BASE}?id=abc&book=123&userInfo=u&course=c",
        {
            "x-plugin-token": "aaa.bbb.ccc",
            "id-token": "ddd.eee.fff",
            "user-agent": "UA",
            "origin": "https://talent.shixizhi.huawei.com",
        },
    )
    auth = _extract_auth(response)  # type: ignore[arg-type]
    assert auth is not None
    assert auth.base_url == "https://ehep.com.cn"
    assert auth.plugin_token == "aaa.bbb.ccc"
    assert auth.id_token == "ddd.eee.fff"
    assert auth.params == {"book": "123", "userInfo": "u", "course": "c"}
    assert auth.headers["accept"] == "application/json"


def test_extract_auth_ignores_foreign_domain() -> None:
    response = FakeResponse("https://example.com/eapi/v2/plugin/book/info?book=1", {"x-plugin-token": "a.b.c"})
    assert _extract_auth(response) is None  # type: ignore[arg-type]


def test_extract_auth_requires_token() -> None:
    response = FakeResponse(f"{BASE}?id=abc&book=123", {"user-agent": "UA"})
    assert _extract_auth(response) is None  # type: ignore[arg-type]


def test_extract_auth_requires_book_param() -> None:
    response = FakeResponse(f"{BASE}?id=abc", {"x-plugin-token": "a.b.c"})
    assert _extract_auth(response) is None  # type: ignore[arg-type]


def test_extract_auth_strips_ephemeral_params() -> None:
    response = FakeResponse(
        f"{BASE}?id=abc&book=9&limit=10&env=prod&keyword=x",
        {"x-plugin-token": "a.b.c"},
    )
    auth = _extract_auth(response)  # type: ignore[arg-type]
    assert auth is not None
    assert auth.params == {"book": "9"}
    assert auth.id_token is None


def test_extract_change_block() -> None:
    messages = [
        {"type": "talentIframeLoaded", "data": {}},
        {
            "type": "changeBlock",
            "data": {
                "bookId": "123456",
                "externalIds": ["block-1"],
                "readerToken": "aaa.bbb.ccc",
                "isEnglishBook": True,
            },
        },
    ]
    block = extract_change_block(messages)
    assert block == {"book_id": "123456", "reader_token": "aaa.bbb.ccc", "is_english": True}


def test_extract_change_block_requires_book() -> None:
    messages = [{"type": "changeBlock", "data": {"readerToken": "aaa"}}]
    assert extract_change_block(messages) is None


def test_extract_change_block_ignores_non_list() -> None:
    assert extract_change_block({"type": "changeBlock"}) is None


def test_auth_from_change_block() -> None:
    block = {"book_id": "42", "reader_token": "aaa.bbb.ccc", "is_english": False}
    auth = auth_from_change_block(block, id_token="ddd.eee.fff")
    assert auth.base_url == "https://ehep.com.cn"
    assert auth.params == {"book": "42"}
    assert auth.headers["x-plugin-token"] == "aaa.bbb.ccc"
    assert auth.id_token == "ddd.eee.fff"


def test_extract_auth_from_headers_without_all_headers() -> None:
    class SimpleRequest:
        def __init__(self) -> None:
            self.url = f"{BASE}?book=7"
            self.headers: dict[str, Any] = {"x-plugin-token": "a.b.c"}

        def all_headers(self) -> dict[str, Any]:
            raise RuntimeError("not available")

    class SimpleResponse:
        def __init__(self) -> None:
            self.request = SimpleRequest()

    auth = _extract_auth(SimpleResponse())  # type: ignore[arg-type]
    assert auth is not None
    assert auth.params["book"] == "7"
