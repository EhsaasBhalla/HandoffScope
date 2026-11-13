"""Dashboard statistics and overview API router.

Phase 10 — Hardening & Demo.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    QuestionStatus,
    ReviewState,
)
from app.modules.audit.models import AuditEvent
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.projects.models import Project, ProjectMembership
from app.modules.questions.models import Question
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User, WorkspaceMembership

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class DashboardStatsResponse(BaseModel):
    projects_count: int
    active_cases_count: int
    transferred_cases_count: int
    connected_sources_count: int
    pending_reviews_count: int
    open_questions_count: int
    active_cases: list[dict[str, Any]]
    needs_attention: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]


@router.get("/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(
    workspace_id: uuid.UUID | None = Query(None),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Aggregate live metrics for the dashboard view."""
    # Find user's accessible projects scoped strictly to user's workspace memberships
    user_ws_ids = [
        wm.workspace_id
        for wm in db.query(WorkspaceMembership.workspace_id)
        .filter(WorkspaceMembership.user_id == user.id)
        .all()
    ]

    if workspace_id:
        if workspace_id not in user_ws_ids:
            return DashboardStatsResponse(
                projects_count=0,
                active_cases_count=0,
                transferred_cases_count=0,
                connected_sources_count=0,
                pending_reviews_count=0,
                open_questions_count=0,
                active_cases=[],
                needs_attention=[],
                recent_activity=[],
            )
        projects = db.query(Project).filter(Project.workspace_id == workspace_id).all()
    else:
        if not user_ws_ids:
            return DashboardStatsResponse(
                projects_count=0,
                active_cases_count=0,
                transferred_cases_count=0,
                connected_sources_count=0,
                pending_reviews_count=0,
                open_questions_count=0,
                active_cases=[],
                needs_attention=[],
                recent_activity=[],
            )
        projects = db.query(Project).filter(Project.workspace_id.in_(user_ws_ids)).all()

    project_ids = [p.id for p in projects]

    projects_count = len(projects)

    # Connected sources count
    connected_sources_count = (
        db.query(ConnectedSource).filter(ConnectedSource.project_id.in_(project_ids)).count()
        if project_ids
        else 0
    )

    # Cases
    case_query = db.query(HandoverCase)
    if project_ids:
        case_query = case_query.filter(HandoverCase.project_id.in_(project_ids))
    all_cases = case_query.all()

    active_statuses = [
        CaseStatus.DRAFT,
        CaseStatus.CONNECTING,
        CaseStatus.INGESTING,
        CaseStatus.RECONSTRUCTING,
        CaseStatus.NEEDS_INPUT,
        CaseStatus.UNDER_REVIEW,
        CaseStatus.APPROVED,
        CaseStatus.SHARED,
        CaseStatus.PARTIALLY_ACKNOWLEDGED,
        CaseStatus.ACKNOWLEDGED,
    ]
    active_cases_list = [c for c in all_cases if c.status in active_statuses]
    transferred_cases_list = [c for c in all_cases if c.status == CaseStatus.TRANSFERRED]

    active_cases_count = len(active_cases_list)
    transferred_cases_count = len(transferred_cases_list)

    # Pending reviews count
    case_ids = [c.id for c in all_cases]
    pending_reviews_count = 0
    open_questions_count = 0

    if case_ids:
        pending_reviews_count = (
            db.query(Claim)
            .join(TransferPack, Claim.transfer_pack_id == TransferPack.id)
            .filter(
                TransferPack.case_id.in_(case_ids),
                Claim.review_state == ReviewState.PENDING_REVIEW,
            )
            .count()
        )

        open_questions_count = (
            db.query(Question)
            .filter(
                Question.case_id.in_(case_ids),
                Question.status.in_([QuestionStatus.OPEN, QuestionStatus.ANSWERED, QuestionStatus.PENDING_REVIEW, QuestionStatus.DRAFT]),
            )
            .count()
        )

    # Active cases summary list
    project_map = {p.id: p.name for p in projects}
    active_cases_data = []
    for c in active_cases_list[:8]:
        active_cases_data.append({
            "id": str(c.id),
            "case_number": c.case_number,
            "title": c.title,
            "project_name": project_map.get(c.project_id, "Unknown Project"),
            "status": c.status.value,
            "sync_status": c.sync_status.value,
            "transition_type": c.transition_type.value,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "scope_end": c.scope_end.isoformat() if c.scope_end else None,
        })

    # Needs attention list
    needs_attention = []
    if pending_reviews_count > 0:
        needs_attention.append({
            "type": "PENDING_REVIEWS",
            "count": pending_reviews_count,
            "title": f"{pending_reviews_count} claim(s) awaiting review",
            "link": "/review",
            "severity": "high",
        })
    if open_questions_count > 0:
        needs_attention.append({
            "type": "OPEN_QUESTIONS",
            "count": open_questions_count,
            "title": f"{open_questions_count} targeted question(s) open or needing review",
            "link": "/questions",
            "severity": "medium",
        })

    # Check for cases with CHANGED_SINCE_APPROVAL or POTENTIALLY_STALE
    stale_cases = [c for c in all_cases if c.sync_status.value in ("CHANGED_SINCE_APPROVAL", "POTENTIALLY_STALE")]
    if stale_cases:
        needs_attention.append({
            "type": "STALE_CASES",
            "count": len(stale_cases),
            "title": f"{len(stale_cases)} case(s) have stale source records or changes since approval",
            "link": "/sources",
            "severity": "high",
        })

    # Recent activity scoped strictly to user's accessible projects/cases
    recent_activity = []
    if project_ids or case_ids:
        from sqlalchemy import or_
        audit_filters = []
        if project_ids:
            audit_filters.append((AuditEvent.entity_type == "project") & (AuditEvent.entity_id.in_(project_ids)))
        if case_ids:
            audit_filters.append((AuditEvent.entity_type == "handover_case") & (AuditEvent.entity_id.in_(case_ids)))

        recent_events = (
            db.query(AuditEvent)
            .filter(or_(*audit_filters))
            .order_by(AuditEvent.created_at.desc())
            .limit(6)
            .all()
        )
        actor_ids = {e.actor_id for e in recent_events if e.actor_id}
        actors = {u.id: u for u in db.query(User).filter(User.id.in_(actor_ids)).all()} if actor_ids else {}

        for e in recent_events:
            u = actors.get(e.actor_id)
            recent_activity.append({
                "id": str(e.id),
                "created_at": e.created_at.isoformat(),
                "action": e.action,
                "actor_name": u.display_name if u else "System",
                "entity_type": e.entity_type,
                "summary": e.summary,
            })

    return DashboardStatsResponse(
        projects_count=projects_count,
        active_cases_count=active_cases_count,
        transferred_cases_count=transferred_cases_count,
        connected_sources_count=connected_sources_count,
        pending_reviews_count=pending_reviews_count,
        open_questions_count=open_questions_count,
        active_cases=active_cases_data,
        needs_attention=needs_attention,
        recent_activity=recent_activity,
    )
