"""Handover case API router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.db.enums import CaseParticipantRole, CaseStatus
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.handover_cases.schemas import (
    CaseBlockRequest,
    CaseCreateRequest,
    CaseListResponse,
    CaseParticipantResponse,
    CaseResponse,
    CaseStatusTransition,
    ParticipantAddRequest,
)
from app.modules.handover_cases.service import (
    add_participant,
    create_case,
    set_blocked,
    transition_case,
)

router = APIRouter(tags=["Handover Cases"])


def _case_to_response(case: HandoverCase, db: Session) -> CaseResponse:
    """Convert ORM case to response with participants."""
    from app.modules.workspaces.models import User

    participants = []
    for p in case.participants:
        u = db.query(User).filter(User.id == p.user_id).first()
        participants.append(CaseParticipantResponse(
            id=p.id,
            user_id=p.user_id,
            role=p.role.value,
            user_email=u.email if u else None,
            user_display_name=u.display_name if u else None,
        ))

    return CaseResponse(
        id=case.id,
        project_id=case.project_id,
        case_number=case.case_number,
        title=case.title,
        description=case.description,
        transition_type=case.transition_type.value,
        status=case.status.value,
        sync_status=case.sync_status.value,
        is_blocked=case.is_blocked,
        blocked_reason=case.blocked_reason,
        scope_start=case.scope_start,
        scope_end=case.scope_end,
        created_by_id=case.created_by_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        participants=participants,
    )


# ── CRUD ──────────────────────────────────────────────────────

@router.post("/projects/{project_id}/cases", response_model=CaseResponse, status_code=201)
def create_handover_case(
    project_id: uuid.UUID,
    body: CaseCreateRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new handover case in DRAFT status."""
    # Verify project exists
    from app.modules.projects.models import Project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    case = create_case(
        db,
        project_id=project_id,
        title=body.title,
        description=body.description,
        transition_type=body.transition_type,
        scope_start=body.scope_start,
        scope_end=body.scope_end,
        created_by_id=user.id,
        departing_id=body.departing_id,
        reviewer_id=body.reviewer_id,
        recipient_id=body.recipient_id,
    )
    db.commit()
    db.refresh(case)
    return _case_to_response(case, db)


@router.get("/projects/{project_id}/cases", response_model=list[CaseListResponse])
def list_cases(
    project_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List handover cases for a project."""
    cases = (
        db.query(HandoverCase)
        .filter(HandoverCase.project_id == project_id)
        .order_by(HandoverCase.case_number.desc())
        .all()
    )
    return [CaseListResponse(
        id=c.id,
        project_id=c.project_id,
        case_number=c.case_number,
        title=c.title,
        transition_type=c.transition_type.value,
        status=c.status.value,
        is_blocked=c.is_blocked,
        created_at=c.created_at,
    ) for c in cases]


@router.get("/cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: uuid.UUID, user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Get detailed case view."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return _case_to_response(case, db)


@router.patch("/cases/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: uuid.UUID,
    body: CaseCreateRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update case metadata (only in DRAFT)."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if case.status != CaseStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only edit cases in DRAFT status")

    if body.title:
        case.title = body.title
    if body.description is not None:
        case.description = body.description
    if body.scope_start is not None:
        case.scope_start = body.scope_start
    if body.scope_end is not None:
        case.scope_end = body.scope_end

    db.commit()
    db.refresh(case)
    return _case_to_response(case, db)


@router.post("/cases/{case_id}/status", response_model=CaseResponse)
def change_case_status(
    case_id: uuid.UUID,
    body: CaseStatusTransition,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Transition case to a new status."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    try:
        target = CaseStatus(body.target_status)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown status: {body.target_status}")

    case = transition_case(db, case=case, target_status=target, actor_id=user.id, reason=body.reason)
    db.commit()
    db.refresh(case)
    return _case_to_response(case, db)


@router.post("/cases/{case_id}/participants", response_model=CaseParticipantResponse, status_code=201)
def add_case_participant(
    case_id: uuid.UUID,
    body: ParticipantAddRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Add a participant to a case."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    try:
        role = CaseParticipantRole(body.role)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role: {body.role}")

    participant = add_participant(db, case_id=case_id, user_id=body.user_id, role=role, actor_id=user.id)
    db.commit()

    from app.modules.workspaces.models import User
    u = db.query(User).filter(User.id == body.user_id).first()

    return CaseParticipantResponse(
        id=participant.id,
        user_id=participant.user_id,
        role=participant.role.value,
        user_email=u.email if u else None,
        user_display_name=u.display_name if u else None,
    )


@router.patch("/cases/{case_id}/block", response_model=CaseResponse)
def block_case(
    case_id: uuid.UUID,
    body: CaseBlockRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Set or clear the blocked flag on a case."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    case = set_blocked(db, case=case, blocked=body.blocked, reason=body.reason, actor_id=user.id)
    db.commit()
    db.refresh(case)
    return _case_to_response(case, db)
