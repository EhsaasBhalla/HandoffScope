"""Pydantic schemas for LLM structured extraction output.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class EvidenceState(str, Enum):
    SUPPORTED = "SUPPORTED"
    INFERRED = "INFERRED"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class EvidenceReference(BaseModel):
    """A reference to a source record supporting a claim."""

    source_record_id: str = Field(description="UUID or ID of the source_record from the provided context")
    excerpt: Optional[str] = Field(None, description="Relevant text excerpt from the source")
    locator: Optional[str] = Field(None, description="Page, section, or line reference")
    relevance: str = Field(default="Direct factual support", description="Why this evidence supports the claim")
    is_restricted: bool = Field(default=False, description="Whether this evidence has restricted access")


class ExtractedWorkItem(BaseModel):
    """A work item identified from source records."""

    title: str = Field(description="Concise title for the work item")
    description: str = Field(description="What this work item involves")
    current_state: str = Field(description="Current state: e.g., in_progress, completed, blocked, open")
    evidence_state: EvidenceState = Field(default=EvidenceState.SUPPORTED)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    related_source_record_ids: list[str] = Field(default_factory=list)
    assigned_to: Optional[str] = Field(None, description="External username if recorded")
    priority: Optional[str] = Field(None)


class ExtractedDecision(BaseModel):
    """An architectural or technical decision."""

    title: str
    description: str
    rationale: Optional[str] = Field(None, description="Why this decision was made, if recorded")
    author: Optional[str] = Field(None, description="Who made or documented the decision")
    date: Optional[str] = Field(None, description="When the decision was made, if known")
    is_superseded: bool = Field(False, description="Whether a later decision replaces this one")
    evidence_state: EvidenceState = Field(default=EvidenceState.SUPPORTED)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ExtractedDependency(BaseModel):
    """A dependency between components or work items."""

    title: str
    description: str
    dependency_type: str = Field(default="blocks", description="blocks, requires, related_to")
    source_component: Optional[str] = Field(None)
    target_component: Optional[str] = Field(None)
    evidence_state: EvidenceState = Field(default=EvidenceState.INFERRED)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ExtractedRisk(BaseModel):
    """An identified risk or blocker."""

    title: str
    description: str
    impact: Optional[str] = Field(None, description="What happens if this risk materializes")
    mitigation: Optional[str] = Field(None, description="Proposed mitigation if recorded")
    evidence_state: EvidenceState = Field(default=EvidenceState.SUPPORTED)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ExtractedOperationalNote(BaseModel):
    """Operational knowledge: runbooks, workarounds, common failures."""

    title: str
    description: str
    category: str = Field(default="runbook", description="runbook, workaround, troubleshooting, procedure")
    evidence_state: EvidenceState = Field(default=EvidenceState.SUPPORTED)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ExtractedKnowledgeGap(BaseModel):
    """Something that is unknown or missing."""

    title: str
    description: str
    why_it_matters: str
    who_might_know: Optional[str] = Field(None)
    evidence_state: EvidenceState = Field(default=EvidenceState.UNKNOWN)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ExtractedQuestionSuggestion(BaseModel):
    """A suggested question to fill a knowledge gap."""

    question_text: str
    why_it_matters: str
    suggested_respondent: Optional[str] = Field(None)
    related_gap: Optional[str] = Field(None, description="Title of the related knowledge gap")
    priority: str = Field(default="MEDIUM")


class ExtractedNextAction(BaseModel):
    """A suggested next action for the incoming person."""

    title: str
    description: str
    priority: str = Field(default="HIGH")
    prerequisite: Optional[str] = Field(None)
    suggested_assignee: Optional[str] = Field(None)
    evidence_state: EvidenceState = Field(default=EvidenceState.INFERRED)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class CandidateTransferPack(BaseModel):
    """A suggested workstream grouping."""

    name: str = Field(description="E.g., 'Authentication API', 'Payment Integration'")
    description: str
    component_area: Optional[str] = Field(None)
    work_items: list[ExtractedWorkItem] = Field(default_factory=list)
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    dependencies: list[ExtractedDependency] = Field(default_factory=list)
    risks: list[ExtractedRisk] = Field(default_factory=list)
    operational_notes: list[ExtractedOperationalNote] = Field(default_factory=list)
    knowledge_gaps: list[ExtractedKnowledgeGap] = Field(default_factory=list)
    next_actions: list[ExtractedNextAction] = Field(default_factory=list)
    question_suggestions: list[ExtractedQuestionSuggestion] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Top-level extraction output schema."""

    transfer_packs: list[CandidateTransferPack] = Field(default_factory=list)
    unassigned_items: list[ExtractedWorkItem] = Field(
        default_factory=list, description="Items that don't clearly belong to a workstream"
    )
    cross_cutting_risks: list[ExtractedRisk] = Field(default_factory=list)
    cross_cutting_gaps: list[ExtractedKnowledgeGap] = Field(default_factory=list)
