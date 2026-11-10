"""Transfer Packs API router.

Phase 6 & 7 — Transfer Packs & Claims.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.transfer_packs.schemas import TransferPackCreate, TransferPackOut, TransferPackUpdate
from app.modules.workspaces.models import User

router = APIRouter(tags=["transfer-packs"])


def _enrich_pack_out(pack: TransferPack, db: Session) -> TransferPackOut:
    owner = db.query(User).filter(User.id == pack.recorded_owner_id).first() if pack.recorded_owner_id else None
    successor = db.query(User).filter(User.id == pack.suggested_successor_id).first() if pack.suggested_successor_id else None
    claims_count = db.query(Claim).filter(Claim.transfer_pack_id == pack.id).count()

    return TransferPackOut(
        id=pack.id,
        case_id=pack.case_id,
        name=pack.name,
        description=pack.description,
        scope_summary=pack.scope_summary,
        component_area=pack.component_area,
        status=pack.status,
        is_blocked=pack.is_blocked,
        blocked_reason=pack.blocked_reason,
        recorded_owner_id=pack.recorded_owner_id,
        recorded_owner_name=owner.display_name if owner else None,
        suggested_successor_id=pack.suggested_successor_id,
        suggested_successor_name=successor.display_name if successor else None,
        sort_order=pack.sort_order,
        claims_count=claims_count,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


@router.get("/cases/{case_id}/transfer-packs", response_model=list[TransferPackOut])
def list_case_transfer_packs(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all Transfer Packs for a handover case."""
    packs = (
        db.query(TransferPack)
        .filter(TransferPack.case_id == case_id)
        .order_by(TransferPack.sort_order.asc(), TransferPack.created_at.asc())
        .all()
    )
    return [_enrich_pack_out(p, db) for p in packs]


@router.get("/transfer-packs/{pack_id}", response_model=TransferPackOut)
def get_transfer_pack(
    pack_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Get details of a specific Transfer Pack."""
    pack = db.query(TransferPack).filter(TransferPack.id == pack_id).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Transfer Pack not found")
    return _enrich_pack_out(pack, db)


@router.post("/cases/{case_id}/transfer-packs", response_model=TransferPackOut, status_code=status.HTTP_201_CREATED)
def create_transfer_pack(
    case_id: uuid.UUID,
    body: TransferPackCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Manually create a Transfer Pack in a handover case."""
    pack = TransferPack(
        id=uuid.uuid4(),
        case_id=case_id,
        name=body.name,
        description=body.description,
        component_area=body.component_area,
        recorded_owner_id=body.recorded_owner_id,
        suggested_successor_id=body.suggested_successor_id,
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return _enrich_pack_out(pack, db)


@router.patch("/transfer-packs/{pack_id}", response_model=TransferPackOut)
def update_transfer_pack(
    pack_id: uuid.UUID,
    body: TransferPackUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Update details or status of a Transfer Pack."""
    pack = db.query(TransferPack).filter(TransferPack.id == pack_id).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Transfer Pack not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(pack, field, val)

    db.commit()
    db.refresh(pack)
    return _enrich_pack_out(pack, db)
