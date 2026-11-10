"""Abstract base class for file storage backends."""

from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    """Interface for file storage operations.

    Implementations must handle save, load, delete, and existence checks
    for uploaded documents and generated artefacts.
    """

    @abstractmethod
    def save(self, path: str, data: bytes) -> str:
        """Save data to storage and return the canonical storage path."""
        ...

    @abstractmethod
    def load(self, path: str) -> bytes:
        """Load and return file contents from storage."""
        ...

    @abstractmethod
    def delete(self, path: str) -> bool:
        """Delete a file from storage. Returns True if deleted, False if not found."""
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check whether a file exists in storage."""
        ...

    @abstractmethod
    def get_url(self, path: str) -> str:
        """Return a URL or path suitable for serving the file."""
        ...
