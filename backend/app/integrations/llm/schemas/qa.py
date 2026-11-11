"""Pydantic schemas for evidence-grounded AI question answering.

Phase 4 (Gap 2) — Interactive Q&A Draft Generation.
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class QAEvidenceReference(BaseModel):
    """A grounded citation to a permitted source record or accepted claim."""

    source_id: str = Field(description="Exact UUID string of the SOURCE_RECORD or CLAIM from context")
    source_type: Literal["SOURCE_RECORD", "CLAIM"] = Field(default="SOURCE_RECORD")
    title: Optional[str] = None
    excerpt: Optional[str] = Field(None, description="Verbatim supporting quote from the evidence")
    locator: Optional[str] = Field(None, description="Page, section, PR/Issue number, or commit ref")
    relevance: str = Field(default="Supports answer", description="Why this evidence supports or conflicts with the answer")
    is_stale: bool = Field(default=False, description="True if source is flagged potentially stale or changed")


class QuestionAnswerResult(BaseModel):
    """Structured contract returned by both Gemini and Mock providers for Q&A."""

    answer_text: str = Field(description="Evidence-grounded draft answer or explicit gap statement")
    answer_status: Literal["answered", "insufficient", "conflicting"] = Field(
        default="answered",
        description="'answered' if supported, 'insufficient' if unestablished, 'conflicting' if sources contradict",
    )
    evidence_references: list[QAEvidenceReference] = Field(default_factory=list)
    limitations: Optional[str] = Field(None, description="What is missing, uncertain, or potentially stale")
    conflicts: list[str] = Field(default_factory=list, description="Explicit conflicting statements if sources disagree")
    confidence_diagnostic: Optional[float] = Field(
        default=None,
        description="Diagnostic-only grounding ratio; NEVER permits auto-acceptance",
    )
