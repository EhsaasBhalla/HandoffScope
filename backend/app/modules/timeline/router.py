"""Timeline API router.

Phase 5 — Normalisation & Identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import RequireCapability, get_db
from app.modules.timeline import service
from app.modules.timeline.schemas import GitHistoryResponse, TimelineResponse

router = APIRouter(tags=["timeline"])


@router.get(
    "/projects/{project_id}/timeline",
    response_model=TimelineResponse,
    dependencies=[Depends(RequireCapability("project.view"))],
)
def get_project_timeline(
    project_id: uuid.UUID,
    event_type: str | None = Query(default=None, description="Comma-separated event types (e.g. COMMIT,PULL_REQUEST)"),
    actor: str | None = Query(default=None, description="Filter by actor handle, name, or mapped user"),
    search: str | None = Query(default=None, description="Text search in title or summary"),
    date_from: datetime | None = Query(default=None, description="Filter events on or after this timestamp"),
    date_to: datetime | None = Query(default=None, description="Filter events on or before this timestamp"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Retrieve an aggregated, chronological timeline of all events across a project's sources and audit trail."""
    return service.get_project_timeline(
        db,
        project_id,
        event_type=event_type,
        actor=actor,
        search=search,
        date_from=date_from,
        date_to=date_to,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/projects/{project_id}/git-history",
    response_model=GitHistoryResponse,
    dependencies=[Depends(RequireCapability("project.view"))],
)
def get_project_git_history(
    project_id: uuid.UUID,
    search: str | None = Query(default=None, description="Search commit message or SHA"),
    author: str | None = Query(default=None, description="Filter by commit author name or login"),
    source_id: uuid.UUID | None = Query(default=None, description="Filter by connected source repository ID"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Retrieve structured, GitHub-style commit history for a project across its connected repositories."""
    return service.get_project_git_history(
        db,
        project_id,
        search=search,
        author=author,
        source_id=source_id,
        page=page,
        per_page=per_page,
    )
