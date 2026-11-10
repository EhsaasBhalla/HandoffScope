"""ORM models for Handover Version Sharing & Share Grants.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.recipients.models import RecipientAcknowledgement
    from app.modules.reviews.models import HandoverVersion
    from app.modules.workspaces.models import User


class ShareGrant(Base):
    """Explicit grant permitting a successor or stakeholder to access an approved handover version."""

    __tablename__ = "share_grants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    handover_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("handover_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    granted_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    version = relationship("HandoverVersion", foreign_keys=[handover_version_id])
    recipient = relationship("User", foreign_keys=[recipient_user_id])
    granter = relationship("User", foreign_keys=[granted_by])
    revoker = relationship("User", foreign_keys=[revoked_by])

    acknowledgements = relationship(
        "RecipientAcknowledgement",
        back_populates="share_grant",
        cascade="all, delete-orphan",
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
