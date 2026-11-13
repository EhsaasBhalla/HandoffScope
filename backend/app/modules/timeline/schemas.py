"""Timeline schemas — chronological aggregation of source and audit events.

Phase 5 — Normalisation & Identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TimelineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    event_type: str
    title: str
    summary: str | None = None
    actor_name: str | None = None
    actor_external_id: str | None = None
    actor_mapped_user_id: uuid.UUID | None = None
    actor_mapped_user_name: str | None = None
    source_name: str | None = None
    source_type: str = "github"
    url: str | None = None
    metadata: dict[str, Any] | None = None


class TimelineResponse(BaseModel):
    items: list[TimelineItemOut]
    total: int
    page: int
    per_page: int
    total_pages: int
    event_types: list[str]


class GitCommitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sha: str
    short_sha: str
    title: str
    message: str | None = None
    author_name: str | None = None
    author_external_id: str | None = None
    author_mapped_user_id: uuid.UUID | None = None
    author_mapped_user_name: str | None = None
    committed_at: datetime | None = None
    url: str | None = None
    source_id: uuid.UUID
    source_name: str | None = None
    branch: str | None = None
    stats: dict[str, Any] | None = None
    files: list[str] | None = None


class GitHistoryResponse(BaseModel):
    items: list[GitCommitOut]
    total: int
    page: int
    per_page: int
    total_pages: int
