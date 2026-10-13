from __future__ import annotations

import base64
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class DecryptError(RuntimeError):
    pass


def aes_cbc_decrypt_b64(content_b64: str, key_b64: str, iv_b64: str) -> str:
    try:
        key = base64.b64decode(key_b64)
        iv = base64.b64decode(iv_b64)
        data = base64.b64decode(content_b64)
    except (ValueError, TypeError) as exc:
        raise DecryptError(f"invalid base64 in encrypted payload: {exc}") from exc

    if len(iv) != 16:
        raise DecryptError(f"unexpected IV length: {len(iv)} bytes")
    if len(key) not in (16, 24, 32):
        raise DecryptError(f"unexpected AES key length: {len(key)} bytes")

    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        plain = unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise DecryptError(f"failed to unpad decrypted content: {exc}") from exc
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DecryptError(f"decrypted content is not valid UTF-8: {exc}") from exc


def find_cipher_payload(obj: Any) -> dict[str, str] | None:
    candidates: list[dict[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if all(isinstance(node.get(k), str) and node.get(k) for k in ("key", "iv", "content")):
                candidates.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(obj)
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item["content"]))


def decrypt_payload(payload: Any) -> str:
    cipher = find_cipher_payload(payload)
    if cipher is None:
        raise DecryptError("no AES payload (key/iv/content) found in API response")
    return aes_cbc_decrypt_b64(cipher["content"], cipher["key"], cipher["iv"])
