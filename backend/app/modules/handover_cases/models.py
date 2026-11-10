"""Handover Case, CaseParticipant, and CaseSource ORM models."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    CaseSyncStatus,
    TransitionType,
)
from app.db.mixins import TimestampMixin, UUIDMixin


class HandoverCase(UUIDMixin, TimestampMixin, Base):
    """A handover case — the central workflow entity."""

    __tablename__ = "handover_cases"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # Per-project sequential number: ATLAS-1, ATLAS-2, etc.
    case_number: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Transition metadata
    transition_type: Mapped[TransitionType] = mapped_column(nullable=False)

    # Dual-dimension state
    status: Mapped[CaseStatus] = mapped_column(
        default=CaseStatus.DRAFT, server_default="DRAFT", nullable=False, index=True
    )
    sync_status: Mapped[CaseSyncStatus] = mapped_column(
        default=CaseSyncStatus.UNKNOWN_FRESHNESS,
        server_default="UNKNOWN_FRESHNESS",
        nullable=False,
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scope dates
    scope_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    scope_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Creator
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    participants: Mapped[list[CaseParticipant]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    sources: Mapped[list[CaseSource]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "case_number", name="uq_case_number_per_project"),
    )

    def __repr__(self) -> str:
        return f"<HandoverCase #{self.case_number} status={self.status.value}>"


class CaseParticipant(UUIDMixin, TimestampMixin, Base):
    """A user's role within a specific handover case."""

    __tablename__ = "case_participants"
    __table_args__ = (
        UniqueConstraint("case_id", "user_id", "role", name="uq_case_participant_role"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("handover_cases.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[CaseParticipantRole] = mapped_column(nullable=False)

    # Relationships
    case: Mapped[HandoverCase] = relationship(back_populates="participants")

    def __repr__(self) -> str:
        return f"<CaseParticipant user={self.user_id} role={self.role.value}>"


class CaseSource(UUIDMixin, TimestampMixin, Base):
    """Links a connected source to a handover case."""

    __tablename__ = "case_sources"
    __table_args__ = (
        UniqueConstraint("case_id", "connected_source_id", name="uq_case_source"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("handover_cases.id", ondelete="CASCADE"), nullable=False
    )
    connected_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False  # FK to connected_sources added in Phase 4
    )
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    case: Mapped[HandoverCase] = relationship(back_populates="sources")

    def __repr__(self) -> str:
        return f"<CaseSource case={self.case_id} source={self.connected_source_id}>"
