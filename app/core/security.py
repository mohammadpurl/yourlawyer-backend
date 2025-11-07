"""Security utilities (encryption helpers, secrets handling)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(RuntimeError):
    """Raised when encrypted content cannot be processed."""


@lru_cache(maxsize=1)
def _get_cipher() -> Optional[Fernet]:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        return None
    return Fernet(key)


def generate_encryption_key() -> str:
    """Generate a new Fernet key (URL-safe base64)."""

    return Fernet.generate_key().decode("utf-8")


def is_encryption_enabled() -> bool:
    return _get_cipher() is not None


def encrypt_bytes(data: bytes) -> bytes:
    cipher = _get_cipher()
    if cipher is None:
        return data
    return cipher.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    cipher = _get_cipher()
    if cipher is None:
        # Encrypted file present but key missing => security misconfiguration
        raise EncryptionError(
            "Encountered encrypted data but ENCRYPTION_KEY is not configured"
        )
    try:
        return cipher.decrypt(data)
    except InvalidToken as exc:  # pragma: no cover - depends on runtime values
        raise EncryptionError("Failed to decrypt data with provided key") from exc

