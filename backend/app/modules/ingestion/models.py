"""Source record and source event ORM models — normalised ingestion layer."""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
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
from app.db.enums import ProcessingStatus, Sensitivity, SourceRecordType
from app.db.mixins import TimestampMixin, UUIDMixin
from app.modules.workspaces.models import User


class SourceRecord(UUIDMixin, TimestampMixin, Base):
    """A normalised record imported from any source (issue, PR, commit, etc.)."""

    __tablename__ = "source_records"

    connected_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connected_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    record_type: Mapped[SourceRecordType] = mapped_column(nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_mapped_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)  # open, closed, merged
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sensitivity: Mapped[Sensitivity] = mapped_column(default=Sensitivity.GENERAL, nullable=False)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        default=ProcessingStatus.PENDING, nullable=False
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # External timestamps
    external_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    events: Mapped[list[SourceEvent]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )
    author_mapped_user: Mapped["User | None"] = relationship("User", foreign_keys=[author_mapped_user_id])

    __table_args__ = (
        UniqueConstraint(
            "connected_source_id", "record_type", "external_id",
            name="uq_source_record_identity",
        ),
    )

    def __repr__(self) -> str:
        return f"<SourceRecord {self.record_type.value}:{self.external_id}>"


class SourceEvent(UUIDMixin, Base):
    """An event/state change within a source record (comment, review, status change)."""

    __tablename__ = "source_events"

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    record: Mapped[SourceRecord] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("record_id", "event_type", "external_id", name="uq_source_event_identity"),
    )

    def __repr__(self) -> str:
        return f"<SourceEvent {self.event_type} on {self.record_id}>"
