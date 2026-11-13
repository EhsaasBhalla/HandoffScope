"""Base connector protocol, normalized batch DTOs, and safe retryable error handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class ConnectorError(RuntimeError):
    """Safe connector failure without leaking credentials."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class ConnectorAuthError(ConnectorError):
    """Raised on 401/403 credential or scope errors."""


class ConnectorRateLimitError(ConnectorError):
    """Raised on 429 or upstream rate limit exhaustion."""


@dataclass
class NormalizedFetchResult:
    """Normalized records and child events ready for the HandoffScope ingestion pipeline."""

    records: list[dict[str, Any]] = field(default_factory=list)
    events_by_key: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    next_cursor: str | None = None
    partial_errors: list[str] = field(default_factory=list)


class BaseSourceConnector(Protocol):
    """Uniform protocol implemented by GitLab, Jira, and Linear connectors."""

    platform_name: str

    def validate_credentials(self) -> dict[str, Any]:
        """Verify connection and permissions without returning raw credentials."""
        ...

    def fetch_records(
        self,
        *,
        cursor: str | None = None,
        since: datetime | None = None,
    ) -> NormalizedFetchResult:
        """Fetch normalized SourceRecords and SourceEvents incrementally."""
        ...


def parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
