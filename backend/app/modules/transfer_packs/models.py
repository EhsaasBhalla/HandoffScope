"""Transfer pack and claim models."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.enums import (
    ClaimType,
    EvidenceState,
    Freshness,
    Priority,
    ReviewState,
    TransferPackStatus,
)
from app.db.mixins import TimestampMixin, UUIDMixin


class TransferPack(Base, UUIDMixin, TimestampMixin):
    """Transfer pack — a topical or workstream grouping of claims within a handover case."""

    __tablename__ = "transfer_packs"

    case_id = Column(
        ForeignKey("handover_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    scope_summary = Column(Text, nullable=True)
    component_area = Column(String(255), nullable=True)
    status = Column(
        Enum(TransferPackStatus, name="transfer_pack_status_enum"),
        default=TransferPackStatus.DRAFT,
        nullable=False,
        index=True,
    )
    is_blocked = Column(Boolean, default=False, nullable=False)
    blocked_reason = Column(Text, nullable=True)
    recorded_owner_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    suggested_successor_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sort_order = Column(Integer, default=0, nullable=False)

    # Relationships
    case = relationship("HandoverCase", backref="transfer_packs")
    recorded_owner = relationship("User", foreign_keys=[recorded_owner_id])
    suggested_successor = relationship("User", foreign_keys=[suggested_successor_id])
    claims = relationship("Claim", back_populates="transfer_pack", cascade="all, delete-orphan")


class Claim(Base, UUIDMixin, TimestampMixin):
    """Claim — a discrete knowledge unit, decision, risk, or work item with evidence."""

    __tablename__ = "claims"

    transfer_pack_id = Column(
        ForeignKey("transfer_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_type = Column(
        Enum(ClaimType, name="claim_type_enum"),
        nullable=False,
        index=True,
    )
    title = Column(String(500), nullable=False)
    body_text = Column(Text, nullable=True)
    original_body_text = Column(Text, nullable=True)
    review_notes = Column(Text, nullable=True)
    evidence_state = Column(
        Enum(EvidenceState, name="evidence_state_enum"),
        default=EvidenceState.UNKNOWN,
        nullable=False,
        index=True,
    )
    freshness = Column(
        Enum(Freshness, name="freshness_enum"),
        default=Freshness.UNKNOWN_FRESHNESS,
        nullable=False,
        index=True,
    )
    review_state = Column(
        Enum(ReviewState, name="review_state_enum"),
        default=ReviewState.PENDING_REVIEW,
        nullable=False,
        index=True,
    )
    priority = Column(
        Enum(Priority, name="priority_enum"),
        nullable=True,
    )
    reviewed_by = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(Text, nullable=True)  # ISO timestamp
    extraction_run_id = Column(String(100), nullable=True)

    # Relationships
    transfer_pack = relationship("TransferPack", back_populates="claims")
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    evidence_items = relationship("ClaimEvidence", back_populates="claim", cascade="all, delete-orphan")
