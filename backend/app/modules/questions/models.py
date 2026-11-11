"""Question and QuestionResponse domain models."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.enums import Priority, QuestionResponseReviewState, QuestionStatus
from app.db.mixins import TimestampMixin, UUIDMixin
from app.modules.transfer_packs.models import TransferPack, Claim  # noqa: F401


class Question(Base, UUIDMixin, TimestampMixin):
    """Targeted question asked during a handover case to clarify context or knowledge gaps."""

    __tablename__ = "questions"

    case_id = Column(
        ForeignKey("handover_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transfer_pack_id = Column(
        ForeignKey("transfer_packs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    claim_id = Column(
        ForeignKey("claims.id", ondelete="SET NULL"),
        nullable=True,
    )
    question_text = Column(Text, nullable=False)
    why_it_matters = Column(Text, nullable=True)
    suggested_respondent_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_to_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    priority = Column(
        Enum(Priority, name="priority_enum"),
        default=Priority.MEDIUM,
        nullable=True,
    )
    status = Column(
        Enum(QuestionStatus, name="question_status_enum"),
        default=QuestionStatus.OPEN,
        nullable=False,
        index=True,
    )
    due_date = Column(String(50), nullable=True)
    created_by_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    case = relationship("HandoverCase", backref="questions")
    transfer_pack = relationship("TransferPack", backref="questions")
    claim = relationship("Claim", foreign_keys="[Question.claim_id]", backref="questions")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    responses = relationship(
        "QuestionResponse",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionResponse.created_at.asc()",
    )


class QuestionResponse(Base, UUIDMixin, TimestampMixin):
    """Answer provided to a handover question by a respondent."""

    __tablename__ = "question_responses"

    question_id = Column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    respondent_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    response_text = Column(Text, nullable=False)
    review_state = Column(
        Enum(QuestionResponseReviewState, name="question_response_review_enum"),
        default=QuestionResponseReviewState.PENDING_REVIEW,
        nullable=False,
    )
    reviewed_by_id = Column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(Text, nullable=True)
    review_notes = Column(Text, nullable=True)

    # Phase 4 / Gap 2 AI draft & grounding provenance fields
    is_ai_generated = Column(Boolean, default=False, server_default="false", nullable=False)
    ai_provider = Column(String(50), nullable=True)
    ai_model = Column(String(100), nullable=True)
    answer_status = Column(String(30), nullable=True)  # "answered" | "insufficient" | "conflicting"
    evidence_json = Column(JSONB, nullable=True)
    limitations = Column(Text, nullable=True)
    conflicts_json = Column(JSONB, nullable=True)
    provenance_json = Column(JSONB, nullable=True)

    # Relationships
    question = relationship("Question", back_populates="responses")
    respondent = relationship("User", foreign_keys=[respondent_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
