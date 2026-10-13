from __future__ import annotations

import base64
import os

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from hictc_web_scraper.decrypt import (
    DecryptError,
    aes_cbc_decrypt_b64,
    decrypt_payload,
    find_cipher_payload,
)


def encrypt(plaintext: str, key: bytes, iv: bytes) -> str:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("ascii")


def payload(plaintext: str) -> dict:
    key = os.urandom(16)
    iv = os.urandom(16)
    return {
        "success": True,
        "data": {
            "key": base64.b64encode(key).decode("ascii"),
            "iv": base64.b64encode(iv).decode("ascii"),
            "content": encrypt(plaintext, key, iv),
        },
    }


def test_round_trip_html() -> None:
    plaintext = "<p>Chapter 1</p><img src='/x.png'>"
    assert decrypt_payload(payload(plaintext)) == plaintext


def test_round_trip_unicode() -> None:
    plaintext = "<p>数据库 Database 数据库</p>"
    assert decrypt_payload(payload(plaintext)) == plaintext


def test_decrypt_direct_fields() -> None:
    key = os.urandom(16)
    iv = os.urandom(16)
    result = aes_cbc_decrypt_b64(
        encrypt("hello", key, iv),
        base64.b64encode(key).decode("ascii"),
        base64.b64encode(iv).decode("ascii"),
    )
    assert result == "hello"


def test_find_cipher_payload_prefers_longest() -> None:
    short = {"key": "a", "iv": "b", "content": "c"}
    long_content = {"key": "a", "iv": "b", "content": "c" * 50}
    found = find_cipher_payload({"a": [short], "b": {"nested": long_content}})
    assert found is long_content


def test_find_cipher_payload_none() -> None:
    assert find_cipher_payload({"data": {"key": "a", "iv": "b"}}) is None


def test_invalid_key_length() -> None:
    with pytest.raises(DecryptError):
        aes_cbc_decrypt_b64(
            base64.b64encode(b"1234").decode("ascii"),
            base64.b64encode(b"short").decode("ascii"),
            base64.b64encode(os.urandom(16)).decode("ascii"),
        )


def test_missing_payload() -> None:
    with pytest.raises(DecryptError):
        decrypt_payload({"success": True, "data": None})
