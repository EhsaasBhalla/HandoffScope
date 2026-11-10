"""Service layer for Transfer Packs restructuring and state transitions.

Phase 7 — Transfer Packs & Restructuring.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.db.enums import TransferPackStatus
from app.modules.audit.service import create_audit_event
from app.modules.transfer_packs.models import Claim, TransferPack


def move_claims(
    db: Session,
    *,
    target_pack_id: uuid.UUID,
    claim_ids: list[uuid.UUID],
    actor_id: Optional[uuid.UUID] = None,
) -> list[Claim]:
    """Move one or more claims from their current transfer pack into the target pack."""
    target_pack = db.query(TransferPack).filter(TransferPack.id == target_pack_id).first()
    if not target_pack:
        raise ValueError("Target Transfer Pack not found")

    claims = db.query(Claim).filter(Claim.id.in_(claim_ids)).all()
    if not claims:
        raise ValueError("No matching claims found to move")

    moved_claims = []
    source_pack_ids = set()

    for claim in claims:
        if claim.transfer_pack_id != target_pack_id:
            source_pack_ids.add(claim.transfer_pack_id)
            claim.transfer_pack_id = target_pack_id
            moved_claims.append(claim)

    db.flush()

    if actor_id:
        create_audit_event(
            db,
            actor_id=actor_id,
            action="pack.claims_moved",
            entity_type="transfer_pack",
            entity_id=target_pack_id,
            details={
                "target_pack_id": str(target_pack_id),
                "moved_count": len(moved_claims),
                "claim_ids": [str(c.id) for c in moved_claims],
                "source_pack_ids": [str(sp) for sp in source_pack_ids],
            },
            summary=f"Moved {len(moved_claims)} claim(s) into Transfer Pack '{target_pack.name}'",
        )

    db.commit()
    for c in moved_claims:
        db.refresh(c)
    return moved_claims


def merge_packs(
    db: Session,
    *,
    target_pack_id: uuid.UUID,
    source_pack_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
) -> TransferPack:
    """Merge all claims from source_pack into target_pack, then delete the source_pack."""
    if target_pack_id == source_pack_id:
        raise ValueError("Cannot merge a Transfer Pack into itself")

    target_pack = db.query(TransferPack).filter(TransferPack.id == target_pack_id).first()
    if not target_pack:
        raise ValueError("Target Transfer Pack not found")

    source_pack = db.query(TransferPack).filter(TransferPack.id == source_pack_id).first()
    if not source_pack:
        raise ValueError("Source Transfer Pack not found")

    if target_pack.case_id != source_pack.case_id:
        raise ValueError("Cannot merge Transfer Packs belonging to different handover cases")

    # Move all claims from source to target
    claims = db.query(Claim).filter(Claim.transfer_pack_id == source_pack_id).all()
    source_name = source_pack.name
    claim_count = len(claims)

    for claim in claims:
        claim.transfer_pack_id = target_pack_id
        claim.transfer_pack = target_pack

    source_pack.claims = []
    db.flush()

    # Delete source pack
    db.delete(source_pack)
    db.flush()

    if actor_id:
        create_audit_event(
            db,
            actor_id=actor_id,
            action="pack.merged",
            entity_type="transfer_pack",
            entity_id=target_pack_id,
            details={
                "target_pack_id": str(target_pack_id),
                "source_pack_id": str(source_pack_id),
                "source_pack_name": source_name,
                "claims_moved_count": claim_count,
            },
            summary=f"Merged '{source_name}' ({claim_count} claims) into '{target_pack.name}'",
        )

    db.commit()
    db.refresh(target_pack)
    return target_pack


def split_pack(
    db: Session,
    *,
    source_pack_id: uuid.UUID,
    new_pack_name: str,
    claim_ids: list[uuid.UUID],
    description: Optional[str] = None,
    component_area: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
) -> TransferPack:
    """Split selected claims out of an existing Transfer Pack into a newly created pack."""
    source_pack = db.query(TransferPack).filter(TransferPack.id == source_pack_id).first()
    if not source_pack:
        raise ValueError("Source Transfer Pack not found")

    if not claim_ids:
        raise ValueError("At least one claim must be selected to split into a new pack")

    claims = (
        db.query(Claim)
        .filter(Claim.id.in_(claim_ids), Claim.transfer_pack_id == source_pack_id)
        .all()
    )
    if not claims:
        raise ValueError("No matching claims found in the source pack")

    new_pack = TransferPack(
        id=uuid.uuid4(),
        case_id=source_pack.case_id,
        name=new_pack_name,
        description=description or f"Split from {source_pack.name}",
        component_area=component_area or source_pack.component_area,
        status=TransferPackStatus.DRAFT,
        recorded_owner_id=source_pack.recorded_owner_id,
        suggested_successor_id=source_pack.suggested_successor_id,
        sort_order=source_pack.sort_order + 1,
    )
    db.add(new_pack)
    db.flush()

    for claim in claims:
        claim.transfer_pack_id = new_pack.id

    db.flush()

    if actor_id:
        create_audit_event(
            db,
            actor_id=actor_id,
            action="pack.split",
            entity_type="transfer_pack",
            entity_id=new_pack.id,
            details={
                "source_pack_id": str(source_pack_id),
                "source_pack_name": source_pack.name,
                "new_pack_id": str(new_pack.id),
                "new_pack_name": new_pack_name,
                "claims_moved_count": len(claims),
            },
            summary=f"Split {len(claims)} claim(s) from '{source_pack.name}' into new pack '{new_pack_name}'",
        )

    db.commit()
    db.refresh(new_pack)
    return new_pack


VALID_PACK_TRANSITIONS: dict[TransferPackStatus, set[TransferPackStatus]] = {
    TransferPackStatus.DRAFT: {
        TransferPackStatus.NEEDS_EVIDENCE,
        TransferPackStatus.NEEDS_INPUT,
        TransferPackStatus.READY_FOR_REVIEW,
        TransferPackStatus.UNDER_REVIEW,
    },
    TransferPackStatus.NEEDS_EVIDENCE: {
        TransferPackStatus.READY_FOR_REVIEW,
        TransferPackStatus.NEEDS_INPUT,
        TransferPackStatus.DRAFT,
    },
    TransferPackStatus.NEEDS_INPUT: {
        TransferPackStatus.READY_FOR_REVIEW,
        TransferPackStatus.NEEDS_EVIDENCE,
        TransferPackStatus.DRAFT,
    },
    TransferPackStatus.READY_FOR_REVIEW: {
        TransferPackStatus.UNDER_REVIEW,
        TransferPackStatus.DRAFT,
    },
    TransferPackStatus.UNDER_REVIEW: {
        TransferPackStatus.APPROVED,
        TransferPackStatus.NEEDS_INPUT,
        TransferPackStatus.NEEDS_EVIDENCE,
        TransferPackStatus.READY_FOR_REVIEW,
    },
    TransferPackStatus.APPROVED: {
        TransferPackStatus.SHARED,
        TransferPackStatus.STALE,
        TransferPackStatus.UNDER_REVIEW,
    },
    TransferPackStatus.SHARED: {
        TransferPackStatus.PARTIALLY_ACCEPTED,
        TransferPackStatus.ACCEPTED,
        TransferPackStatus.STALE,
        TransferPackStatus.UNDER_REVIEW,
    },
    TransferPackStatus.PARTIALLY_ACCEPTED: {
        TransferPackStatus.ACCEPTED,
        TransferPackStatus.STALE,
    },
    TransferPackStatus.ACCEPTED: {
        TransferPackStatus.STALE,
    },
    TransferPackStatus.STALE: {
        TransferPackStatus.UNDER_REVIEW,
        TransferPackStatus.DRAFT,
    },
}


def transition_pack_status(
    db: Session,
    *,
    pack_id: uuid.UUID,
    new_status: TransferPackStatus,
    actor_id: Optional[uuid.UUID] = None,
) -> TransferPack:
    """Transition a Transfer Pack's status according to the state machine."""
    pack = db.query(TransferPack).filter(TransferPack.id == pack_id).first()
    if not pack:
        raise ValueError("Transfer Pack not found")

    current_status = pack.status
    if current_status == new_status:
        return pack

    allowed = VALID_PACK_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise ValueError(f"Invalid transition from {current_status.value} to {new_status.value}")

    pack.status = new_status
    db.flush()

    if actor_id:
        create_audit_event(
            db,
            actor_id=actor_id,
            action="pack.status_changed",
            entity_type="transfer_pack",
            entity_id=pack.id,
            details={"old_status": current_status.value, "new_status": new_status.value},
            summary=f"Changed status of pack '{pack.name}' from {current_status.value} to {new_status.value}",
        )

    db.commit()
    db.refresh(pack)
    return pack
