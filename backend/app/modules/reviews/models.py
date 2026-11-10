"""Review and immutable version snapshot domain models.

Phase 8 — Review & Approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDMixin
from app.modules.handover_cases.models import HandoverCase  # noqa: F401
from app.modules.workspaces.models import User  # noqa: F401


class HandoverVersion(Base, UUIDMixin, TimestampMixin):
    """Immutable snapshot of an approved Handover Case state.

    Contains full frozen JSON snapshot of all transfer packs, claims, grounded citations,
    and metadata at the exact moment of approval.
    """

    __tablename__ = "handover_versions"
    __table_args__ = (
        UniqueConstraint("case_id", "version_number", name="uq_case_version_number"),
    )

    case_id = Column(
        ForeignKey("handover_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    approved_by_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    snapshot_json = Column(JSON, nullable=False)
    is_current = Column(Boolean, default=False, nullable=False, index=True)
    amendment_reason = Column(Text, nullable=True)
    previous_version_id = Column(
        ForeignKey("handover_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    case = relationship("HandoverCase", backref="versions")
    approver = relationship("User", foreign_keys=[approved_by_id])
    previous_version = relationship("HandoverVersion", remote_side="HandoverVersion.id")
