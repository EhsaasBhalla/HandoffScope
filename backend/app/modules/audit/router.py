"""Audit event API router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.audit.service import list_audit_events

router = APIRouter(prefix="/audit", tags=["Audit"])


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    created_at: str
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_email: str | None = None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    details: dict | None = None
    summary: str | None = None

    model_config = {"from_attributes": True}


@router.get("/events", response_model=list[AuditEventResponse])
def get_audit_events(
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    actor_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List audit events (paginated, optionally filtered)."""
    from app.modules.workspaces.models import User

    events = list_audit_events(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        search=search,
        limit=limit,
        offset=offset,
    )
    # Collect unique actor IDs for bulk lookup
    actor_ids = {e.actor_id for e in events if e.actor_id}
    users = {}
    if actor_ids:
        user_records = db.query(User).filter(User.id.in_(actor_ids)).all()
        users = {u.id: u for u in user_records}

    results = []
    for e in events:
        actor = users.get(e.actor_id) if e.actor_id else None
        results.append(AuditEventResponse(
            id=e.id,
            created_at=e.created_at.isoformat(),
            actor_id=e.actor_id,
            actor_name=actor.display_name if actor else None,
            actor_email=actor.email if actor else None,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            details=e.details,
            summary=e.summary,
        ))
    return results
