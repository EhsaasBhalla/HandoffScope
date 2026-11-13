"""Local filesystem storage backend."""

import logging
import os
from pathlib import Path

from app.core.config import settings
from app.storage.base import StorageBackend

logger = logging.getLogger("handoffscope.storage")


class LocalStorageBackend(StorageBackend):
    """Stores files on the local filesystem under UPLOAD_DIR."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or settings.UPLOAD_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _full_path(self, path: str) -> Path:
        clean = path.replace("\\", "/").lstrip("/")
        full = (self.base_dir / clean).resolve()
        # Prevent path traversal
        try:
            full.relative_to(self.base_dir)
        except ValueError:
            raise ValueError("Path traversal detected")
        return full

    def save(self, path: str, data: bytes) -> str:
        full = self._full_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        logger.info("Saved file: %s (%d bytes)", path, len(data))
        return str(path)

    def load(self, path: str) -> bytes:
        full = self._full_path(path)
        if not full.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return full.read_bytes()

    def delete(self, path: str) -> bool:
        full = self._full_path(path)
        if full.exists():
            full.unlink()
            logger.info("Deleted file: %s", path)
            return True
        return False

    def exists(self, path: str) -> bool:
        return self._full_path(path).exists()

    def get_url(self, path: str) -> str:
        return f"/storage/{path}"
