"""Canonical JSON serialization, SHA-256 hashing, and dedicated Ed25519 key management."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.config import settings

_KEY_LOCK = threading.Lock()
_CACHED_SIGNER: SigningMaterial | None = None


@dataclass(frozen=True)
class SigningMaterial:
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    public_key_pem: bytes
    public_key_fingerprint: str
    key_id: str
    persistent_configured: bool


def _normalize_unicode(obj: Any) -> Any:
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [_normalize_unicode(item) for item in obj]
    if isinstance(obj, dict):
        return {_normalize_unicode(str(k)): _normalize_unicode(v) for k, v in obj.items()}
    return obj


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize data deterministically to UTF-8 JSON (strictly forbidding NaN/Infinity)."""
    normalized = _normalize_unicode(payload)
    text = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return lowercase SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    """Compute SHA-256 fingerprint over SubjectPublicKeyInfo DER bytes."""
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return f"SHA256:{sha256_hex(der)}"


def _load_or_create_private_key() -> tuple[Ed25519PrivateKey, bool]:
    """Load dedicated Ed25519 signing key outside DB/Git, never derived from JWT SECRET_KEY."""
    env_pem = (settings.EXPORT_SIGNING_PRIVATE_KEY_PEM or "").strip()
    if env_pem:
        normalized_pem = env_pem.replace("\\n", "\n").encode("utf-8")
        key = serialization.load_pem_private_key(normalized_pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("EXPORT_SIGNING_PRIVATE_KEY_PEM must be an Ed25519 private key")
        return key, True

    key_path = Path(settings.EXPORT_SIGNING_KEY_PATH or "./storage/export_signing_key.pem")
    if key_path.exists():
        raw = key_path.read_bytes()
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Stored export signing key is not Ed25519")
        return key, True

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem_bytes)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key, False


def get_signing_material() -> SigningMaterial:
    """Return process-cached dedicated Ed25519 signing material."""
    global _CACHED_SIGNER
    if _CACHED_SIGNER is not None:
        return _CACHED_SIGNER

    with _KEY_LOCK:
        if _CACHED_SIGNER is not None:
            return _CACHED_SIGNER
        priv, persistent_configured = _load_or_create_private_key()
        pub = priv.public_key()
        pub_pem = pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fp = compute_public_key_fingerprint(pub)
        configured_id = (settings.EXPORT_SIGNING_KEY_ID or "").strip()
        key_id = configured_id or f"ed25519-{fp.split(':', 1)[1][:16]}"
        _CACHED_SIGNER = SigningMaterial(
            private_key=priv,
            public_key=pub,
            public_key_pem=pub_pem,
            public_key_fingerprint=fp,
            key_id=key_id,
            persistent_configured=persistent_configured,
        )
        return _CACHED_SIGNER


def get_trusted_fingerprints() -> set[str]:
    """Return active and historically trusted signer key SHA-256 fingerprints."""
    material = get_signing_material()
    trusted = {material.public_key_fingerprint}
    extra = (settings.EXPORT_TRUSTED_PUBLIC_KEY_FINGERPRINTS or "").strip()
    if extra:
        for item in extra.split(","):
            val = item.strip()
            if val:
                trusted.add(val)
    return trusted


def sign_manifest_bytes(manifest_bytes: bytes) -> dict[str, Any]:
    """Sign exact manifest JSON bytes with Ed25519 and return detached signature envelope."""
    material = get_signing_material()
    sig_raw = material.private_key.sign(manifest_bytes)
    return {
        "algorithm": "Ed25519",
        "signing_key_id": material.key_id,
        "signer_label": "HandoffScope Application Signer",
        "public_key_fingerprint": material.public_key_fingerprint,
        "manifest_sha256": sha256_hex(manifest_bytes),
        "signature_b64": base64.b64encode(sig_raw).decode("ascii"),
    }


def verify_ed25519_signature(
    *,
    public_key_pem: bytes,
    manifest_bytes: bytes,
    signature_envelope: dict[str, Any],
) -> tuple[bool, str | None, str | None]:
    """Verify Ed25519 signature envelope over exact manifest bytes.

    Returns ``(is_valid, fingerprint, error_message)``.
    """
    try:
        pub = serialization.load_pem_public_key(public_key_pem)
    except Exception as exc:
        return False, None, f"Invalid public_key.pem: {exc}"

    if not isinstance(pub, Ed25519PublicKey):
        return False, None, "public_key.pem is not an Ed25519 key"

    fp = compute_public_key_fingerprint(pub)
    if signature_envelope.get("algorithm") != "Ed25519":
        return False, fp, "Unsupported signature algorithm"

    expected_sha = sha256_hex(manifest_bytes)
    if signature_envelope.get("manifest_sha256") != expected_sha:
        return False, fp, "Manifest digest in certificate.sig does not match manifest.json"

    try:
        sig_bytes = base64.b64decode(signature_envelope.get("signature_b64", ""), validate=True)
    except Exception as exc:
        return False, fp, f"Malformed base64 signature: {exc}"

    try:
        pub.verify(sig_bytes, manifest_bytes)
    except InvalidSignature:
        return False, fp, "Ed25519 cryptographic signature verification failed"
    except Exception as exc:
        return False, fp, f"Signature verification error: {exc}"

    return True, fp, None
