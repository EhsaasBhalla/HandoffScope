"""Document ORM model and upload models."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ProcessingStatus, Sensitivity
from app.db.mixins import TimestampMixin, UUIDMixin


class Document(UUIDMixin, TimestampMixin, Base):
    """An uploaded document attached to a project."""

    __tablename__ = "documents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        default=ProcessingStatus.PENDING, nullable=False
    )
    sensitivity: Mapped[Sensitivity] = mapped_column(
        default=Sensitivity.GENERAL, nullable=False
    )

    # Extracted content
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Upload context
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project")
    uploaded_by: Mapped["User | None"] = relationship("User", foreign_keys=[uploaded_by_id])

    def __repr__(self) -> str:
        return f"<Document {self.original_filename} status={self.processing_status.value}>"
