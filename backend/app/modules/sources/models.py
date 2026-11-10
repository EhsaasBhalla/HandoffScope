"""Connected sources, sync runs, and GitHub installation ORM models.

Phase 4 — Sources & Document Ingestion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import ConnectionStatus, SourceType, SyncRunStatus
from app.db.mixins import TimestampMixin, UUIDMixin


class ConnectedSource(UUIDMixin, TimestampMixin, Base):
    """An external data source connected to a project."""

    __tablename__ = "connected_sources"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[SourceType] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    connection_status: Mapped[ConnectionStatus] = mapped_column(
        default=ConnectionStatus.PENDING, nullable=False
    )
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    connected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    sync_runs: Mapped[list[SyncRun]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "source_type", "external_id", name="uq_source_identity"),
    )

    def __repr__(self) -> str:
        return f"<ConnectedSource {self.source_type.value}:{self.name}>"


class SyncRun(UUIDMixin, TimestampMixin, Base):
    """A single synchronisation run for a connected source."""

    __tablename__ = "sync_runs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connected_sources.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[SyncRunStatus] = mapped_column(
        default=SyncRunStatus.PENDING, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    source: Mapped[ConnectedSource] = relationship(back_populates="sync_runs")

    def __repr__(self) -> str:
        return f"<SyncRun {self.id} status={self.status.value}>"


class GitHubInstallation(UUIDMixin, TimestampMixin, Base):
    """Stores GitHub App installation details."""

    __tablename__ = "github_installations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    installation_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    account_login: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(50), default="Organization")
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    installed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<GitHubInstallation {self.account_login} #{self.installation_id}>"
