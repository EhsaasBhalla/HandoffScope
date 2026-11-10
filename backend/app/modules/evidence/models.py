"""Evidence and extraction run ORM models.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import EvidenceType, ExtractionRunStatus
from app.db.mixins import TimestampMixin, UUIDMixin
from app.modules.documents.models import Document
from app.modules.handover_cases.models import HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.transfer_packs.models import Claim


class ExtractionRun(UUIDMixin, Base):
    """Provenance record for an AI-assisted structured extraction run."""

    __tablename__ = "extraction_runs"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("handover_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_template_version: Mapped[str] = mapped_column(String(50), default="v1", nullable=False)
    input_source_record_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    token_usage_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ExtractionRunStatus] = mapped_column(
        Enum(ExtractionRunStatus, name="extraction_run_status_enum"),
        default=ExtractionRunStatus.COMPLETED,
        nullable=False,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validated_output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    case: Mapped["HandoverCase"] = relationship("HandoverCase")


class ClaimEvidence(UUIDMixin, Base):
    """Grounded reference connecting a claim to a source record or document section."""

    __tablename__ = "claim_evidence"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, name="evidence_type_enum"),
        default=EvidenceType.DIRECT_REFERENCE,
        nullable=False,
    )
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    claim: Mapped["Claim"] = relationship("Claim", back_populates="evidence_items")
    source_record: Mapped["SourceRecord | None"] = relationship("SourceRecord")
    document: Mapped["Document | None"] = relationship("Document")
