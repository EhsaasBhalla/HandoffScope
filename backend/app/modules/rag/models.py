"""ORM models for version-pinned KnowledgeChunks and persistent Conversational RAG threads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import Sensitivity
from app.db.mixins import TimestampMixin, UUIDMixin

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class KnowledgeChunk(UUIDMixin, Base):
    """Derived semantic/lexical chunk indexed from a HandoverVersion snapshot or draft scope."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "context_mode",
            "source_kind",
            "source_ref_id",
            "content_hash",
            "version_id",
            name="uq_knowledge_chunk_identity",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("handover_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("handover_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # APPROVED_SNAPSHOT | DRAFT_CONTEXT
    context_mode: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # CLAIM | SOURCE_RECORD | DOCUMENT_SECTION | QA_ANSWER
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_ref_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)

    sensitivity: Mapped[Sensitivity] = mapped_column(
        SAEnum(Sensitivity, name="sensitivity_enum", create_constraint=False, native_enum=False),
        default=Sensitivity.GENERAL,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    locator_json: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)

    embedding_json: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class RagThread(UUIDMixin, TimestampMixin, Base):
    """Persistent version-pinned Q&A chat thread scoped strictly to a user & handover case."""

    __tablename__ = "rag_threads"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("handover_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    context_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    pinned_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("handover_versions.id", ondelete="SET NULL"), nullable=True
    )
    pinned_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    messages: Mapped[list[RagMessage]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="RagMessage.created_at.asc()",
    )


class RagMessage(UUIDMixin, Base):
    """Single user question or grounded assistant turn inside a RagThread."""

    __tablename__ = "rag_messages"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rag_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    grounding_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    citations_json: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    thread: Mapped[RagThread] = relationship(back_populates="messages")
