"""API router for Recipient Access, Successor Projections, and Responsibility Acceptance.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.recipients.models import ResponsibilityAssignment
from app.modules.recipients.schemas import (
    AssignResponsibilityRequest,
    DeclineResponsibilityRequest,
    RecipientAcknowledgementOut,
    ResponsibilityAssignmentOut,
    SuccessorCaseSummaryOut,
    SuccessorContinuationViewOut,
)
from app.modules.recipients.service import (
    _to_assignment_out,
    accept_responsibility,
    acknowledge_handover,
    assign_responsibility,
    build_recipient_projection,
    decline_responsibility,
    list_successor_cases,
)
from app.modules.workspaces.models import User

router = APIRouter(tags=["Recipients & Responsibility"])


@router.get("/recipient/cases", response_model=list[SuccessorCaseSummaryOut])
def get_my_successor_cases(
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all handover cases shared with or assigned to the current user as successor."""
    return list_successor_cases(db, user_id=user.id)


@router.get("/recipient/cases/{case_id}", response_model=SuccessorContinuationViewOut)
def get_successor_continuation_view(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve the tailored, permission-filtered continuation view for a successor."""
    try:
        return build_recipient_projection(db, case_id=case_id, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/recipient/cases/{case_id}/acknowledge", response_model=RecipientAcknowledgementOut)
def acknowledge_case_receipt_endpoint(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Successor formally confirms receipt and opens the handover."""
    try:
        ack = acknowledge_handover(db, case_id=case_id, user_id=user.id)
        return RecipientAcknowledgementOut.model_validate(ack)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/cases/{case_id}/responsibilities", response_model=list[ResponsibilityAssignmentOut])
def list_case_responsibilities(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all responsibility assignments for transfer packs in this case."""
    assignments = (
        db.query(ResponsibilityAssignment)
        .join(ResponsibilityAssignment.transfer_pack)
        .filter(ResponsibilityAssignment.transfer_pack.has(case_id=case_id))
        .all()
    )
    return [_to_assignment_out(a) for a in assignments]


@router.post("/cases/{case_id}/responsibilities", response_model=ResponsibilityAssignmentOut, status_code=status.HTTP_201_CREATED)
def assign_case_responsibility_endpoint(
    case_id: uuid.UUID,
    body: AssignResponsibilityRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Assign operational responsibility for a Transfer Pack to a successor."""
    try:
        assignment = assign_responsibility(
            db,
            transfer_pack_id=body.transfer_pack_id,
            assigned_user_id=body.assigned_user_id,
            assigned_by=user.id,
            handover_version_id=body.handover_version_id,
        )
        return _to_assignment_out(assignment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/responsibility-assignments/{assignment_id}/accept", response_model=ResponsibilityAssignmentOut)
def accept_responsibility_endpoint(
    assignment_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Successor formally accepts ownership of an assigned pack."""
    try:
        assignment = accept_responsibility(db, assignment_id=assignment_id, user_id=user.id)
        return _to_assignment_out(assignment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/responsibility-assignments/{assignment_id}/decline", response_model=ResponsibilityAssignmentOut)
def decline_responsibility_endpoint(
    assignment_id: uuid.UUID,
    body: DeclineResponsibilityRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Successor formally declines ownership of an assigned pack with a documented reason."""
    try:
        assignment = decline_responsibility(
            db,
            assignment_id=assignment_id,
            user_id=user.id,
            reason=body.reason,
        )
        return _to_assignment_out(assignment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
