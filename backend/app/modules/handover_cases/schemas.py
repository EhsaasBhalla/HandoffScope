"""Handover case Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class CaseCreateRequest(BaseModel):
    title: str
    description: str | None = None
    transition_type: str
    scope_start: date | None = None
    scope_end: date | None = None
    departing_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID | None = None
    recipient_id: uuid.UUID | None = None


class CaseStatusTransition(BaseModel):
    target_status: str
    reason: str | None = None


class CaseBlockRequest(BaseModel):
    blocked: bool
    reason: str | None = None


class ParticipantAddRequest(BaseModel):
    user_id: uuid.UUID
    role: str


class CaseParticipantResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role: str
    user_email: str | None = None
    user_display_name: str | None = None

    model_config = {"from_attributes": True}


class CaseResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    case_number: int
    title: str
    description: str | None = None
    transition_type: str
    status: str
    sync_status: str
    is_blocked: bool
    blocked_reason: str | None = None
    scope_start: date | None = None
    scope_end: date | None = None
    created_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    participants: list[CaseParticipantResponse] = []

    model_config = {"from_attributes": True}


class CaseListResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    case_number: int
    title: str
    description: str | None = None
    transition_type: str
    status: str
    is_blocked: bool
    created_at: datetime

    model_config = {"from_attributes": True}
