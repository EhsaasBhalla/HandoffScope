"""API router for Reviews, Claim Review Actions, and Immutable Handover Versions.

Phase 8 — Review & Approval.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db, require_case_capability
from app.modules.evidence.models import ClaimEvidence
from app.modules.evidence.router import _enrich_evidence_out
from app.modules.evidence.schemas import ClaimDetailOut
from app.modules.evidence.service import review_claim
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.schemas import (
    CreateVersionRequest,
    HandoverVersionDetailOut,
    HandoverVersionOut,
    ReviewClaimRequest,
    ReviewQueueSummaryOut,
)
from app.modules.reviews.service import (
    create_approved_version,
    get_review_queue_summary,
    get_version_detail,
    list_case_versions,
)
from app.modules.workspaces.models import User

router = APIRouter(tags=["Reviews & Approval"])


def _to_version_out(v: HandoverVersion) -> HandoverVersionOut:
    snap = v.snapshot_json or {}
    meta = snap.get("metadata", {})
    packs_list = snap.get("transfer_packs") or snap.get("packs") or []
    computed_claims = sum(
        p.get("claims_count", len(p.get("claims", []))) if isinstance(p, dict) else 0
        for p in packs_list
    )
    return HandoverVersionOut(
        id=v.id,
        case_id=v.case_id,
        version_number=v.version_number,
        approved_by_id=v.approved_by_id,
        approved_by_name=v.approver.display_name if v.approver else meta.get("approved_by_name"),
        approved_at=v.approved_at,
        is_current=v.is_current,
        amendment_reason=v.amendment_reason,
        previous_version_id=v.previous_version_id,
        created_at=v.created_at,
        total_packs=meta.get("total_packs", len(packs_list)),
        total_claims=meta.get("total_claims", computed_claims),
    )


@router.get("/cases/{case_id}/review-queue", response_model=ReviewQueueSummaryOut)
def get_case_review_queue(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get review status summary, claim stats, and approval readiness checklist."""
    require_case_capability(db, user, case_id, "review.view")
    try:
        return get_review_queue_summary(db, case_id=case_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/claims/{claim_id}/review", response_model=ClaimDetailOut)
def review_claim_endpoint(
    claim_id: uuid.UUID,
    body: ReviewClaimRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Review a claim (accept, edit_and_accept, reject, or request clarification)."""
    from app.modules.transfer_packs.models import Claim, TransferPack

    claim_obj = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim_obj:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim_obj.transfer_pack_id:
        pack_obj = db.query(TransferPack).filter(TransferPack.id == claim_obj.transfer_pack_id).first()
        if pack_obj and pack_obj.case_id:
            require_case_capability(db, user, pack_obj.case_id, "review.submit")

    try:
        claim = review_claim(
            db,
            claim_id=claim_id,
            user_id=user.id,
            action=body.action,
            edited_body=body.edited_body,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    evidence_records = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == claim.id)
        .order_by(ClaimEvidence.created_at.asc())
        .all()
    )
    evidence_items = [_enrich_evidence_out(ev, db) for ev in evidence_records]

    return ClaimDetailOut(
        id=claim.id,
        transfer_pack_id=claim.transfer_pack_id,
        claim_type=claim.claim_type,
        title=claim.title,
        body_text=claim.body_text,
        original_body_text=claim.original_body_text,
        review_notes=claim.review_notes,
        evidence_state=claim.evidence_state,
        freshness=claim.freshness,
        review_state=claim.review_state,
        priority=claim.priority,
        reviewed_by=claim.reviewed_by,
        reviewed_at=claim.reviewed_at,
        extraction_run_id=claim.extraction_run_id,
        evidence_count=len(evidence_items),
        created_at=claim.created_at,
        updated_at=claim.updated_at,
        evidence=evidence_items,
    )


@router.post("/cases/{case_id}/versions", response_model=HandoverVersionDetailOut, status_code=status.HTTP_201_CREATED)
def create_version_endpoint(
    case_id: uuid.UUID,
    body: CreateVersionRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create an approved immutable version snapshot for a handover case."""
    try:
        version = create_approved_version(
            db,
            case_id=case_id,
            user_id=user.id,
            amendment_reason=body.amendment_reason,
            override_blockers=body.override_blockers,
            override_reason=body.override_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return HandoverVersionDetailOut(
        **_to_version_out(version).model_dump(),
        snapshot_json=version.snapshot_json,
    )


@router.get("/cases/{case_id}/versions", response_model=list[HandoverVersionOut])
def list_versions_endpoint(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all approved versions for a handover case."""
    versions = list_case_versions(db, case_id=case_id)
    return [_to_version_out(v) for v in versions]


@router.get("/versions/{version_id}", response_model=HandoverVersionDetailOut)
def get_version_endpoint(
    version_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get full details of an approved version including the frozen snapshot."""
    try:
        version = get_version_detail(db, version_id=version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return HandoverVersionDetailOut(
        **_to_version_out(version).model_dump(),
        snapshot_json=version.snapshot_json,
    )
