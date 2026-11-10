"""Audit event service — create and query audit events."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent

logger = logging.getLogger("handoffscope.audit")


def create_audit_event(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    details: dict | None = None,
    summary: str | None = None,
) -> AuditEvent:
    """Create and persist an audit event."""
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        summary=summary,
    )
    db.add(event)
    db.flush()
    logger.info(
        "Audit: %s %s/%s by %s — %s",
        action, entity_type, entity_id, actor_id, summary or "",
    )
    return event


def list_audit_events(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """Query audit events with optional filters."""
    query = db.query(AuditEvent)
    if entity_type:
        query = query.filter(AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditEvent.entity_id == entity_id)
    if actor_id:
        query = query.filter(AuditEvent.actor_id == actor_id)
    if action:
        query = query.filter(AuditEvent.action.ilike(f"%{action}%"))
    if search:
        query = query.filter(
            (AuditEvent.summary.ilike(f"%{search}%")) |
            (AuditEvent.action.ilike(f"%{search}%")) |
            (AuditEvent.entity_type.ilike(f"%{search}%"))
        )
    return query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit).all()
