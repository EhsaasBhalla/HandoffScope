"""Audit event ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDMixin


class AuditEvent(UUIDMixin, Base):
    """Immutable audit log entry.

    Uses SET NULL on foreign keys so events survive parent deletion.
    """

    __tablename__ = "audit_events"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Who performed the action — SET NULL if user is deleted
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # What action
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Target entity type + ID (polymorphic)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Structured detail payload
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Human-readable summary
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditEvent {self.action} on {self.entity_type}/{self.entity_id}>"
