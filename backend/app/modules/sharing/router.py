"""API router for Handover Version Sharing & Share Grants.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.recipients.models import RecipientAcknowledgement
from app.modules.sharing.models import ShareGrant
from app.modules.sharing.schemas import CreateShareGrantRequest, ShareGrantOut
from app.modules.sharing.service import (
    create_share_grant,
    list_case_share_grants,
    list_version_share_grants,
    revoke_share_grant,
)
from app.modules.workspaces.models import User

router = APIRouter(tags=["Sharing & Grants"])


def _to_share_grant_out(grant: ShareGrant, db: Session) -> ShareGrantOut:
    ack = (
        db.query(RecipientAcknowledgement)
        .filter(RecipientAcknowledgement.share_grant_id == grant.id)
        .first()
    )
    v = grant.version
    case = v.case if v else None

    return ShareGrantOut(
        id=grant.id,
        handover_version_id=grant.handover_version_id,
        version_number=v.version_number if v else 0,
        case_id=case.id if case else uuid.UUID(int=0),
        case_title=case.title if case else "",
        recipient_user_id=grant.recipient_user_id,
        recipient_name=grant.recipient.display_name if grant.recipient else "Unknown",
        recipient_email=grant.recipient.email if grant.recipient else "",
        granted_by=grant.granted_by,
        granter_name=grant.granter.display_name if grant.granter else None,
        granted_at=grant.granted_at,
        revoked_at=grant.revoked_at,
        is_active=grant.is_active,
        is_acknowledged=ack is not None,
        acknowledged_at=ack.acknowledged_at if ack else None,
    )


@router.post("/versions/{version_id}/share", response_model=ShareGrantOut, status_code=status.HTTP_201_CREATED)
def share_version_endpoint(
    version_id: uuid.UUID,
    body: CreateShareGrantRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Grant an incoming successor or stakeholder access to an approved version."""
    try:
        grant = create_share_grant(
            db,
            version_id=version_id,
            recipient_user_id=body.recipient_user_id,
            granted_by=user.id,
        )
        return _to_share_grant_out(grant, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/versions/{version_id}/shares", response_model=list[ShareGrantOut])
def list_version_shares_endpoint(
    version_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all share grants issued for a specific version."""
    grants = list_version_share_grants(db, version_id=version_id)
    return [_to_share_grant_out(g, db) for g in grants]


@router.get("/cases/{case_id}/shares", response_model=list[ShareGrantOut])
def list_case_shares_endpoint(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all share grants issued for a handover case across versions."""
    grants = list_case_share_grants(db, case_id=case_id)
    return [_to_share_grant_out(g, db) for g in grants]


@router.delete("/share-grants/{grant_id}", response_model=ShareGrantOut)
def revoke_share_grant_endpoint(
    grant_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Revoke an active share grant."""
    try:
        grant = revoke_share_grant(db, grant_id=grant_id, revoked_by=user.id)
        return _to_share_grant_out(grant, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
