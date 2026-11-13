"""Pydantic schemas for Conversational RAG Assistant."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class RagAskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    thread_id: Optional[uuid.UUID] = None
    context_mode: Optional[str] = Field(
        default=None,
        description="APPROVED_SNAPSHOT (default when approved version exists) or DRAFT_CONTEXT (Lead/Reviewer only)",
    )
    version_id: Optional[uuid.UUID] = None


class RagCitationOut(BaseModel):
    chunk_id: str
    source_kind: str
    source_ref_id: str
    title: str
    excerpt: str
    locator: Optional[str] = None
    url: Optional[str] = None
    pack_name: Optional[str] = None


class RagMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content_text: str
    grounding_status: Optional[str] = None
    citations: list[RagCitationOut] = []
    limitations: Optional[str] = None
    retrieval_mode: Optional[str] = None
    provider_name: Optional[str] = None
    model_used: Optional[str] = None
    latency_ms: Optional[int] = None
    created_at: datetime


class RagThreadOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    context_mode: str
    pinned_version_id: Optional[uuid.UUID] = None
    pinned_version_number: Optional[int] = None
    title: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class RagThreadDetailOut(RagThreadOut):
    messages: list[RagMessageOut] = []


class RagAskResponse(BaseModel):
    thread: RagThreadOut
    user_message: RagMessageOut
    assistant_message: RagMessageOut
    restricted_evidence_excluded: bool = False


class RagReindexRequest(BaseModel):
    context_mode: str = "APPROVED_SNAPSHOT"
    version_id: Optional[uuid.UUID] = None


class RagReindexResultOut(BaseModel):
    case_id: uuid.UUID
    context_mode: str
    version_id: Optional[uuid.UUID] = None
    chunks_indexed: int
    embedding_provider_mode: str
    embedding_model: str
    embedding_dimension: int
