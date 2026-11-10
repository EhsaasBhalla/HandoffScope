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
