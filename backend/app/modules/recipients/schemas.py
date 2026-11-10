"""Pydantic schemas for Recipient Continuation View and Responsibility Transfer.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import ResponsibilityAcceptanceStatus


class RecipientAcknowledgementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    share_grant_id: uuid.UUID
    handover_version_id: uuid.UUID
    user_id: uuid.UUID
    acknowledged_at: datetime


class AssignResponsibilityRequest(BaseModel):
    transfer_pack_id: uuid.UUID
    assigned_user_id: uuid.UUID
    handover_version_id: Optional[uuid.UUID] = None


class DeclineResponsibilityRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


class ResponsibilityAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transfer_pack_id: uuid.UUID
    transfer_pack_name: str
    transfer_pack_area: Optional[str] = None
    handover_version_id: uuid.UUID
    version_number: int
    assigned_user_id: uuid.UUID
    assignee_name: str
    assigned_by: Optional[uuid.UUID] = None
    assigned_at: datetime
    status: str
    responded_at: Optional[datetime] = None
    decline_reason: Optional[str] = None


class SuccessorProjectedClaimOut(BaseModel):
    id: uuid.UUID
    transfer_pack_id: uuid.UUID
    claim_type: str
    title: str
    body_text: str
    original_body_text: Optional[str] = None
    evidence_state: str
    freshness: str
    review_state: str
    priority: str
    is_restricted_withheld: bool = False
    evidence_count: int = 0
    evidence_snippets: list[str] = []


class SuccessorProjectedPackOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    component_area: Optional[str] = None
    status: str
    claims_count: int
    claims: list[SuccessorProjectedClaimOut] = []
    assignment: Optional[ResponsibilityAssignmentOut] = None


class SuccessorCaseSummaryOut(BaseModel):
    id: uuid.UUID
    case_number: int
    title: str
    status: str
    project_name: str
    current_version_number: Optional[int] = None
    is_acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    assigned_packs_count: int = 0
    total_packs_count: int = 0


class SuccessorContinuationViewOut(BaseModel):
    case_id: uuid.UUID
    case_number: int
    title: str
    transition_type: str
    status: str
    project_id: uuid.UUID
    project_name: str
    departing_contributor_name: Optional[str] = None
    current_version_number: Optional[int] = None
    version_id: Optional[uuid.UUID] = None
    is_acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    share_grant_id: Optional[uuid.UUID] = None

    # Core Continuation Pillars:
    # 1. "What am I taking over?"
    responsibilities: list[ResponsibilityAssignmentOut] = []
    transfer_packs: list[SuccessorProjectedPackOut] = []

    # 2. "What are my next actions?"
    next_actions: list[SuccessorProjectedClaimOut] = []

    # 3. "What's unfinished?"
    unfinished_items: list[dict[str, Any]] = []

    # 4. "What do I not have access to? / Access Blockers"
    access_blockers: list[dict[str, Any]] = []

    stats: dict[str, int] = {
        "total_packs": 0,
        "assigned_packs": 0,
        "accepted_packs": 0,
        "declined_packs": 0,
        "pending_packs": 0,
        "next_actions_count": 0,
        "access_blockers_count": 0,
    }
