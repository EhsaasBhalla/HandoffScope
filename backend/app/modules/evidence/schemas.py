"""Evidence and claim schemas.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.enums import ClaimType, EvidenceState, EvidenceType, Freshness, Priority, ReviewState


class ClaimEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    claim_id: uuid.UUID
    source_record_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    excerpt: Optional[str] = None
    locator: Optional[str] = None
    evidence_type: EvidenceType
    is_restricted: bool = False
    created_at: datetime

    # Denormalised source metadata for frontend cards
    source_title: Optional[str] = None
    source_type: Optional[str] = None
    source_author: Optional[str] = None
    source_url: Optional[str] = None
    source_timestamp: Optional[datetime] = None


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transfer_pack_id: uuid.UUID
    claim_type: ClaimType
    title: str
    body_text: Optional[str] = None
    original_body_text: Optional[str] = None
    review_notes: Optional[str] = None
    evidence_state: EvidenceState
    freshness: Freshness
    review_state: ReviewState
    priority: Optional[Priority] = None
    reviewed_by: Optional[uuid.UUID] = None
    reviewed_at: Optional[str] = None
    extraction_run_id: Optional[str] = None
    evidence_count: int = 0
    created_at: datetime
    updated_at: datetime


class ClaimDetailOut(ClaimOut):
    evidence: list[ClaimEvidenceOut] = []


class ClaimUpdate(BaseModel):
    title: Optional[str] = None
    body_text: Optional[str] = None
    priority: Optional[Priority] = None
    review_state: Optional[ReviewState] = None
    evidence_state: Optional[EvidenceState] = None


class ReviewClaimRequest(BaseModel):
    action: str  # "accept" | "edit_and_accept" | "reject" | "needs_clarification" | "resubmit"
    edited_body: Optional[str] = None
    reason: Optional[str] = None
