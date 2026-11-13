"""Document schemas — Pydantic models for uploaded documents."""

from __future__ import annotations

import uuid
from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size: int
    processing_status: str
    sensitivity: str
    page_count: int | None = None
    section_count: int | None = None
    created_at: str

    model_config = {"from_attributes": True}
