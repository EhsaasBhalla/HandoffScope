"""Identity mapping ORM models — mapping external source identities to HandoffScope users.

Phase 5 — Normalisation & Identity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import IdentityConfidence
from app.db.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.modules.projects.models import Project
    from app.modules.workspaces.models import User


class IdentityMapping(UUIDMixin, TimestampMixin, Base):
    """Maps an external author/contributor identity to an internal HandoffScope user.

    Constraints:
      UNIQUE(project_id, external_provider, external_id)
    """

    __tablename__ = "identity_mappings"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_provider: Mapped[str] = mapped_column(String(50), default="github", nullable=False)
    external_username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)

    mapped_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confidence: Mapped[IdentityConfidence] = mapped_column(
        default=IdentityConfidence.UNMATCHED, nullable=False
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project")
    mapped_user: Mapped["User | None"] = relationship("User", foreign_keys=[mapped_user_id])
    verifier: Mapped["User | None"] = relationship("User", foreign_keys=[verified_by])

    __table_args__ = (
        UniqueConstraint(
            "project_id", "external_provider", "external_id",
            name="uq_project_identity_mapping"
        ),
    )

    def __repr__(self) -> str:
        return f"<IdentityMapping {self.external_provider}:{self.external_username} -> {self.mapped_user_id} ({self.confidence.value})>"
