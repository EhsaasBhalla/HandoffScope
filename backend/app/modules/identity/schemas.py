"""Identity mapping schemas — request/response payloads for contributor identity resolution.

Phase 5 — Normalisation & Identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import IdentityConfidence


class IdentityMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    external_provider: str
    external_username: str
    external_id: str
    mapped_user_id: uuid.UUID | None = None
    mapped_user_name: str | None = None
    mapped_user_email: str | None = None
    confidence: IdentityConfidence
    verified_by: uuid.UUID | None = None
    verified_by_name: str | None = None
    contributions_count: int = 0
    created_at: datetime
    updated_at: datetime


class IdentityMappingUpdate(BaseModel):
    action: Literal["confirm", "reject", "remap"] = Field(
        description="Action to take: 'confirm' verifies mapping; 'reject' unmaps; 'remap' points to another user."
    )
    mapped_user_id: uuid.UUID | None = Field(
        default=None,
        description="Optional target user ID when confirming or remapping."
    )


class IdentityMappingCreate(BaseModel):
    external_provider: str = Field(default="github", description="Source provider, e.g. 'github'")
    external_username: str = Field(..., description="External handle, e.g. GitHub username")
    external_id: str | None = Field(default=None, description="External user ID or handle")
    mapped_user_id: uuid.UUID | None = None
    confidence: IdentityConfidence = IdentityConfidence.SUGGESTED


class IdentityCoverageOut(BaseModel):
    project_id: uuid.UUID
    total_external_authors: int
    verified_count: int
    suggested_count: int
    unmatched_count: int
    total_source_records: int
    mapped_source_records: int
    coverage_percent: float
