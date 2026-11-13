"""Shared StorageBackend factory resolving local disk vs S3/R2 object storage."""

from __future__ import annotations

from app.core.config import settings
from app.storage.base import StorageBackend
from app.storage.local_storage import LocalStorageBackend
from app.storage.s3_storage import S3CompatibleStorageBackend


def get_storage_backend() -> StorageBackend:
    """Instantiate configured storage backend cleanly."""
    mode = (settings.STORAGE_BACKEND or "local").strip().lower()
    if mode in ("s3", "r2"):
        return S3CompatibleStorageBackend(
            endpoint_url=settings.S3_ENDPOINT_URL,
            bucket=settings.S3_BUCKET,
            access_key_id=settings.S3_ACCESS_KEY_ID,
            secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region=settings.S3_REGION,
        )
    return LocalStorageBackend()


def load_stored_bytes(storage_path: str) -> bytes:
    """Load bytes from either S3 pointer (`s3://...`) or local storage gracefully."""
    if storage_path.startswith("s3://") and (settings.STORAGE_BACKEND or "local").strip().lower() in ("s3", "r2"):
        return get_storage_backend().load(storage_path)
    if storage_path.startswith("s3://"):
        return get_storage_backend().load(storage_path)
    return LocalStorageBackend().load(storage_path)
