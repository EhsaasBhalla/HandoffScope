"""Reconstruction and extraction run schemas.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.db.enums import ExtractionRunStatus


class ReconstructionTriggerResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    packs_created: int
    claims_created: int
    evidence_linked: int
    message: str
    provider_mode: str = "live"  # "live" | "mock" | "mock_fallback"
    model_used: str = ""
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    context_stats: Optional[dict[str, Any]] = None


class ExtractionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    model_name: str
    status: ExtractionRunStatus
    prompt_template_version: str
    token_usage_input: Optional[int] = None
    token_usage_output: Optional[int] = None
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None
    provider_mode: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    context_stats: Optional[dict[str, Any]] = None
    created_at: datetime
