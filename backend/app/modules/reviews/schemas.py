"""Schemas for Reviews, Claim Review Actions, and Version Approvals.

Phase 8 — Review & Approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ReviewClaimRequest(BaseModel):
    action: str  # "accept" | "edit_and_accept" | "reject" | "needs_clarification" | "resubmit"
    edited_body: Optional[str] = None
    reason: Optional[str] = None


class CreateVersionRequest(BaseModel):
    amendment_reason: Optional[str] = None
    override_blockers: bool = False
    override_reason: Optional[str] = None


class ReviewBlockerOut(BaseModel):
    code: str
    category: str  # "claims" | "questions" | "case" | "structure" | "security"
    severity: str  # "critical" | "non_critical"
    message: str
    related_object_id: Optional[str] = None
    related_object_type: Optional[str] = None
    overridable: bool = False
    required_permission: Optional[str] = None


class HandoverVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    version_number: int
    approved_by_id: Optional[uuid.UUID] = None
    approved_by_name: Optional[str] = None
    approved_at: datetime
    is_current: bool = False
    amendment_reason: Optional[str] = None
    previous_version_id: Optional[uuid.UUID] = None
    created_at: datetime
    total_packs: int = 0
    total_claims: int = 0


class HandoverVersionDetailOut(HandoverVersionOut):
    snapshot_json: dict[str, Any]


class ReviewQueueSummaryOut(BaseModel):
    case_id: uuid.UUID
    case_number: int
    case_title: str
    case_status: str
    can_approve: bool
    blocking_reasons: list[str] = []
    blockers: list[ReviewBlockerOut] = []
    has_critical_blockers: bool = False
    can_override: bool = False
    is_blocked: bool = False
    blocked_reason: Optional[str] = None
    total_claims: int = 0
    pending_review_count: int = 0
    accepted_count: int = 0
    edited_and_accepted_count: int = 0
    rejected_count: int = 0
    needs_clarification_count: int = 0
    open_questions_count: int = 0
    awaiting_question_review_count: int = 0
    critical_questions_count: int = 0
    total_packs: int = 0
    approved_packs_count: int = 0
    versions_count: int = 0
    current_version_number: Optional[int] = None
