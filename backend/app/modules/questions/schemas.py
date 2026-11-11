"""Pydantic schemas for Questions & Responses."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel


class QuestionResponseCreate(BaseModel):
    response_text: str


class QuestionReviewRequest(BaseModel):
    action: str  # "accept" | "reject" | "amend"
    notes: Optional[str] = None
    amended_text: Optional[str] = None


class QuestionCreate(BaseModel):
    case_id: uuid.UUID
    question_text: str
    why_it_matters: Optional[str] = None
    transfer_pack_id: Optional[uuid.UUID] = None
    claim_id: Optional[uuid.UUID] = None
    assigned_to_id: Optional[uuid.UUID] = None
    priority: str = "MEDIUM"
    due_date: Optional[str] = None


class QuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    why_it_matters: Optional[str] = None
    transfer_pack_id: Optional[uuid.UUID] = None
    claim_id: Optional[uuid.UUID] = None
    assigned_to_id: Optional[uuid.UUID] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None


class QuestionResponseOut(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    respondent_id: Optional[uuid.UUID] = None
    respondent_name: Optional[str] = None
    response_text: str
    review_state: str
    reviewed_by_id: Optional[uuid.UUID] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None
    is_ai_generated: bool = False
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    answer_status: Optional[str] = None
    evidence_references: list[dict[str, Any]] = []
    limitations: Optional[str] = None
    conflicts: list[str] = []
    provenance: Optional[dict[str, Any]] = None
    created_at: str

    model_config = {"from_attributes": True}


class QuestionOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_number: Optional[int] = None
    case_title: Optional[str] = None
    transfer_pack_id: Optional[uuid.UUID] = None
    transfer_pack_name: Optional[str] = None
    claim_id: Optional[uuid.UUID] = None
    claim_title: Optional[str] = None
    question_text: str
    why_it_matters: Optional[str] = None
    assigned_to_id: Optional[uuid.UUID] = None
    assigned_to_name: Optional[str] = None
    priority: str
    status: str
    due_date: Optional[str] = None
    created_by_id: Optional[uuid.UUID] = None
    created_by_name: Optional[str] = None
    created_at: str
    responses: list[QuestionResponseOut] = []
    promotion_result: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}
