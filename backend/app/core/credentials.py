"""Authenticated symmetric encryption for third-party connector & OAuth credentials."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

_PREFIX = "enc:v1:"
_SECRET_CONFIG_KEYS = ("access_token", "api_token", "private_token", "client_secret", "refresh_token")


def _build_fernet() -> Fernet:
    raw = (settings.CREDENTIAL_ENCRYPTION_KEY or settings.SECRET_KEY or "handoffscope-credential-encryption-key-fallback").strip()
    raw_secret = (raw if raw else "handoffscope-credential-encryption-key-fallback").encode("utf-8")
    try:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"handoffscope-credential-v1",
            info=b"connector-token-encryption",
        )
        derived = hkdf.derive(raw_secret)
        return Fernet(base64.urlsafe_b64encode(derived))
    except Exception:
        key = hashlib.sha256(raw_secret).digest()
        return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a secret string using authenticated Fernet encryption."""
    if plaintext is None:
        return None
    stripped = plaintext.strip()
    if not stripped:
        return ""
    if stripped.startswith(_PREFIX):
        return stripped
    try:
        token = _build_fernet().encrypt(stripped.encode("utf-8")).decode("ascii")
        return f"{_PREFIX}{token}"
    except Exception:
        return stripped


def decrypt_secret(ciphertext: str | None) -> str:
    """Decrypt an encrypted token, returning empty string if blank or unreadable."""
    if not ciphertext:
        return ""
    raw = ciphertext.strip()
    if not raw:
        return ""
    if raw.startswith(_PREFIX):
        payload = raw[len(_PREFIX) :]
        try:
            return _build_fernet().decrypt(payload.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError, Exception):
            return ""
    # Legacy unencrypted row fallback
    return raw


def encrypt_source_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of ConnectedSource.config with any credential fields encrypted."""
    if not config:
        return None
    out = dict(config)
    for key in _SECRET_CONFIG_KEYS:
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = encrypt_secret(val)
        elif key in out and not val:
            out.pop(key, None)
    return out


def sanitize_source_config_for_api(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip raw credentials before returning source metadata to API callers."""
    if not config:
        return None
    out: dict[str, Any] = {}
    token_configured = False
    for key, val in config.items():
        if key in _SECRET_CONFIG_KEYS:
            if val:
                token_configured = True
            continue
        out[key] = val
    out["token_configured"] = token_configured
    return out
