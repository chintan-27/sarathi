"""Encrypt/decrypt API keys stored in config.json.

Keys are encrypted with Fernet using a machine-derived key so that the
config file is not plaintext-readable on another machine.
"""
from __future__ import annotations

import base64
import hashlib
import os
import platform


def _derive_key() -> bytes:
    identity = (
        f"{platform.node()}:"
        f"{os.getenv('USER', os.getenv('USERNAME', 'sarathi'))}"
    )
    raw = hashlib.pbkdf2_hmac(
        "sha256", identity.encode(), b"sarathi-keystore", 100_000
    )
    return base64.urlsafe_b64encode(raw)


def encrypt(plaintext: str) -> str:
    from cryptography.fernet import Fernet
    return Fernet(_derive_key()).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a value encrypted by `encrypt()`. Returns plaintext unchanged if
    it was never encrypted (e.g. manually edited config)."""
    if not ciphertext:
        return ciphertext
    from cryptography.fernet import Fernet, InvalidToken
    try:
        return Fernet(_derive_key()).decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ciphertext  # treat as plaintext fallback
