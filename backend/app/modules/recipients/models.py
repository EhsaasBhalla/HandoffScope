"""ORM models for Recipient Acknowledgements, Responsibility Assignments, and Acceptances.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.enums import ResponsibilityAcceptanceStatus

if TYPE_CHECKING:
    from app.modules.reviews.models import HandoverVersion
    from app.modules.sharing.models import ShareGrant
    from app.modules.transfer_packs.models import TransferPack
    from app.modules.workspaces.models import User


class RecipientAcknowledgement(Base):
    """Immutable audit record confirming a successor has received and acknowledged a handover version."""

    __tablename__ = "recipient_acknowledgements"
    __table_args__ = (
        UniqueConstraint("share_grant_id", "user_id", name="uq_recipient_ack_grant_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    share_grant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("share_grants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    handover_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("handover_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    acknowledged_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    share_grant = relationship("ShareGrant", back_populates="acknowledgements")
    version = relationship("HandoverVersion")
    user = relationship("User")


class ResponsibilityAssignment(Base):
    """Maps operational ownership of a Transfer Pack to a designated incoming successor."""

    __tablename__ = "responsibility_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_pack_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transfer_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    handover_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("handover_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    transfer_pack = relationship("TransferPack")
    version = relationship("HandoverVersion")
    assignee = relationship("User", foreign_keys=[assigned_user_id])
    assigner = relationship("User", foreign_keys=[assigned_by])

    acceptance = relationship(
        "ResponsibilityAcceptance",
        uselist=False,
        back_populates="assignment",
        cascade="all, delete-orphan",
    )


class ResponsibilityAcceptance(Base):
    """Formal sign-off by a successor accepting or declining responsibility for a Transfer Pack."""

    __tablename__ = "responsibility_acceptances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    responsibility_assignment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("responsibility_assignments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(
        Enum(ResponsibilityAcceptanceStatus, name="responsibility_acceptance_enum", native_enum=False),
        default=ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE,
        nullable=False,
        index=True,
    )
    responded_at = Column(DateTime(timezone=True), nullable=True)
    decline_reason = Column(Text, nullable=True)

    # Relationships
    assignment = relationship(
        "ResponsibilityAssignment",
        back_populates="acceptance",
    )
    user = relationship("User")
