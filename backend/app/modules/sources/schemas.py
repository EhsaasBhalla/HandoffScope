"""Sources schemas — Pydantic models for connected sources and sync runs."""

from __future__ import annotations

import uuid
from pydantic import BaseModel


class SyncRunResponse(BaseModel):
    id: uuid.UUID
    status: str
    records_fetched: int
    records_created: int
    records_updated: int
    records_skipped: int = 0
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    model_config = {"from_attributes": True}


class SourceResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_type: str
    name: str
    external_id: str | None = None
    connection_status: str
    config: dict | None = None
    created_at: str
    updated_at: str | None = None
    last_successful_sync_at: str | None = None
    last_sync_run: SyncRunResponse | None = None

    model_config = {"from_attributes": True}


class SourceConnectRequest(BaseModel):
    source_type: str
    name: str
    external_id: str | None = None
    config: dict | None = None


class RefreshRequest(BaseModel):
    simulate_modification: bool = False


class SourceRecordDetailOut(BaseModel):
    id: uuid.UUID
    record_type: str
    external_id: str
    title: str | None = None
    body: str | None = None
    author_name: str | None = None
    state: str | None = None
    url: str | None = None
    sensitivity: str
    external_created_at: str | None = None
    metadata_json: dict | None = None
