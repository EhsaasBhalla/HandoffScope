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
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List audit events (paginated, optionally filtered)."""
    events = list_audit_events(
        db, entity_type=entity_type, entity_id=entity_id, limit=limit, offset=offset,
    )
    results = []
    for e in events:
        results.append(AuditEventResponse(
            id=e.id,
            created_at=e.created_at.isoformat(),
            actor_id=e.actor_id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            details=e.details,
            summary=e.summary,
        ))
    return results
