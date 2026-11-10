"""Project and project membership ORM models."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ProjectRole
from app.db.mixins import TimestampMixin, UUIDMixin


class Project(UUIDMixin, TimestampMixin, Base):
    """A project within a workspace — the scope boundary for handover cases."""

    __tablename__ = "projects"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship(back_populates="projects")
    memberships: Mapped[list[ProjectMembership]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_project_workspace_slug"),
    )

    def __repr__(self) -> str:
        return f"<Project {self.slug}>"


class ProjectMembership(UUIDMixin, TimestampMixin, Base):
    """Links a user to a project with a role."""

    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_project_membership"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ProjectRole] = mapped_column(
        default=ProjectRole.CONTRIBUTOR, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="project_memberships")
    project: Mapped[Project] = relationship(back_populates="memberships")

    def __repr__(self) -> str:
        return f"<ProjectMembership user={self.user_id} proj={self.project_id} role={self.role}>"


# Avoid circular import — import Workspace for relationship resolution
from app.modules.workspaces.models import Workspace  # noqa: E402
