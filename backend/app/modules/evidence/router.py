"""Evidence and claims API router.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.db.enums import ClaimType, EvidenceState, ReviewState
from app.modules.audit.service import create_audit_event
from app.modules.documents.models import Document
from app.modules.evidence.clearance import (
    RESTRICTED_EVIDENCE_PLACEHOLDER,
    get_restricted_claim_ids,
    has_restricted_clearance,
)
from app.modules.evidence.models import ClaimEvidence
from app.modules.evidence.schemas import ClaimDetailOut, ClaimEvidenceOut, ClaimOut, ClaimUpdate
from app.modules.handover_cases.models import HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.sharing.redactor import redact_secrets_inline
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User

router = APIRouter(tags=["evidence"])


def _resolve_user_clearance(
    db: Session,
    request: Request,
    project_id: uuid.UUID | None,
    case_id: uuid.UUID | None,
) -> bool:
    try:
        from app.core.dependencies import get_current_user
        user = get_current_user(request, db)
    except Exception:
        user = None

    if user is None:
        return False

    if project_id is None:
        return True

    return has_restricted_clearance(
        db,
        user_id=user.id,
        project_id=project_id,
        case_id=case_id,
        user=user,
    )


def _enrich_evidence_out(ev: ClaimEvidence, db: Session, allow_restricted: bool = True) -> ClaimEvidenceOut:
    if ev.is_restricted and not allow_restricted:
        return ClaimEvidenceOut(
            id=ev.id,
            claim_id=ev.claim_id,
            source_record_id=None,
            document_id=None,
            excerpt="[WITHHELD BY ACCESS POLICY]",
            locator="Restricted Document Reference",
            evidence_type=ev.evidence_type,
            is_restricted=True,
            created_at=ev.created_at,
            source_title=None,
            source_type=None,
            source_author=None,
            source_url=None,
            source_timestamp=None,
        )

    source_title = None
    source_type = None
    source_author = None
    source_url = None
    source_timestamp = None

    if ev.source_record_id:
        sr = db.query(SourceRecord).filter(SourceRecord.id == ev.source_record_id).first()
        if sr:
            source_title = sr.title
            source_type = sr.record_type.value if hasattr(sr.record_type, "value") else str(sr.record_type)
            source_author = sr.author_name or sr.author_external_id
            source_url = sr.url
            source_timestamp = sr.external_created_at or sr.created_at
    elif ev.document_id:
        doc = db.query(Document).filter(Document.id == ev.document_id).first()
        if doc:
            source_title = doc.original_filename
            source_type = "DOCUMENT"
            source_timestamp = doc.created_at

    excerpt = ev.excerpt
    if not allow_restricted and excerpt:
        excerpt = redact_secrets_inline(excerpt).redacted_text

    return ClaimEvidenceOut(
        id=ev.id,
        claim_id=ev.claim_id,
        source_record_id=ev.source_record_id,
        document_id=ev.document_id,
        excerpt=excerpt,
        locator=ev.locator,
        evidence_type=ev.evidence_type,
        is_restricted=ev.is_restricted,
        created_at=ev.created_at,
        source_title=source_title,
        source_type=source_type,
        source_author=source_author,
        source_url=source_url,
        source_timestamp=source_timestamp,
    )


def _project_claim_out(
    c: Claim,
    ev_count: int,
    is_restricted: bool,
    allow_restricted: bool,
) -> ClaimOut:
    if is_restricted and not allow_restricted:
        body_text = RESTRICTED_EVIDENCE_PLACEHOLDER
        original_body_text = None
        review_notes = None
    else:
        body_text = c.body_text
        original_body_text = c.original_body_text
        review_notes = c.review_notes
        if not allow_restricted:
            if body_text:
                body_text = redact_secrets_inline(body_text).redacted_text
            if original_body_text:
                original_body_text = redact_secrets_inline(original_body_text).redacted_text

    return ClaimOut(
        id=c.id,
        transfer_pack_id=c.transfer_pack_id,
        claim_type=c.claim_type,
        title=c.title,
        body_text=body_text,
        original_body_text=original_body_text,
        review_notes=review_notes,
        evidence_state=c.evidence_state,
        freshness=c.freshness,
        review_state=c.review_state,
        priority=c.priority,
        reviewed_by=c.reviewed_by,
        reviewed_at=c.reviewed_at,
        extraction_run_id=c.extraction_run_id,
        evidence_count=ev_count,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/cases/{case_id}/claims", response_model=list[ClaimOut])
def list_case_claims(
    case_id: uuid.UUID,
    request: Request,
    claim_type: ClaimType | None = Query(default=None),
    evidence_state: EvidenceState | None = Query(default=None),
    review_state: ReviewState | None = Query(default=None),
    transfer_pack_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """List all claims belonging to a Handover Case across all its Transfer Packs."""
    packs = db.query(TransferPack).filter(TransferPack.case_id == case_id).all()
    if not packs:
        return []

    pack_ids = [p.id for p in packs]
    if transfer_pack_id:
        if transfer_pack_id in pack_ids:
            pack_ids = [transfer_pack_id]
        else:
            return []

    query = db.query(Claim).filter(Claim.transfer_pack_id.in_(pack_ids))
    if claim_type:
        query = query.filter(Claim.claim_type == claim_type)
    if evidence_state:
        query = query.filter(Claim.evidence_state == evidence_state)
    if review_state:
        query = query.filter(Claim.review_state == review_state)

    claims = query.order_by(Claim.created_at.desc()).all()

    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    allow_restricted = _resolve_user_clearance(
        db, request, project_id=case.project_id if case else None, case_id=case_id
    )
    restricted_ids = get_restricted_claim_ids(db, claim_ids=[c.id for c in claims]) if claims else set()

    result = []
    for c in claims:
        ev_count = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == c.id).count()
        is_restr = c.id in restricted_ids
        result.append(_project_claim_out(c, ev_count, is_restr, allow_restricted))
    return result


@router.get("/transfer-packs/{pack_id}/claims", response_model=list[ClaimOut])
def list_pack_claims(
    pack_id: uuid.UUID,
    request: Request,
    claim_type: ClaimType | None = Query(default=None),
    evidence_state: EvidenceState | None = Query(default=None),
    review_state: ReviewState | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """List all claims belonging to a Transfer Pack with filtering."""
    pack = db.query(TransferPack).filter(TransferPack.id == pack_id).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Transfer Pack not found")

    query = db.query(Claim).filter(Claim.transfer_pack_id == pack_id)
    if claim_type:
        query = query.filter(Claim.claim_type == claim_type)
    if evidence_state:
        query = query.filter(Claim.evidence_state == evidence_state)
    if review_state:
        query = query.filter(Claim.review_state == review_state)

    claims = query.order_by(Claim.created_at.desc()).all()

    case_id = pack.case_id
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first() if case_id else None
    allow_restricted = _resolve_user_clearance(
        db, request, project_id=case.project_id if case else None, case_id=case_id
    )
    restricted_ids = get_restricted_claim_ids(db, claim_ids=[c.id for c in claims]) if claims else set()

    result = []
    for c in claims:
        ev_count = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == c.id).count()
        is_restr = c.id in restricted_ids
        result.append(_project_claim_out(c, ev_count, is_restr, allow_restricted))
    return result


@router.get("/claims/{claim_id}", response_model=ClaimDetailOut)
def get_claim_detail(
    claim_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Retrieve full details of a claim including all grounded evidence references."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    pack = claim.transfer_pack
    case_id = pack.case_id if pack else None
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first() if case_id else None
    allow_restricted = _resolve_user_clearance(
        db, request, project_id=case.project_id if case else None, case_id=case_id
    )

    evidence_records = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == claim.id)
        .order_by(ClaimEvidence.created_at.asc())
        .all()
    )

    is_restr = any(ev.is_restricted for ev in evidence_records)
    evidence_items = [_enrich_evidence_out(ev, db, allow_restricted=allow_restricted) for ev in evidence_records]
    base_out = _project_claim_out(claim, len(evidence_items), is_restr, allow_restricted)

    return ClaimDetailOut(
        **base_out.model_dump(),
        evidence=evidence_items,
    )


@router.get("/claims/{claim_id}/evidence", response_model=list[ClaimEvidenceOut])
def list_claim_evidence(
    claim_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """List all evidence references for a specific claim."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    pack = claim.transfer_pack
    case_id = pack.case_id if pack else None
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first() if case_id else None
    allow_restricted = _resolve_user_clearance(
        db, request, project_id=case.project_id if case else None, case_id=case_id
    )

    evidence_records = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == claim.id)
        .order_by(ClaimEvidence.created_at.asc())
        .all()
    )

    return [_enrich_evidence_out(ev, db, allow_restricted=allow_restricted) for ev in evidence_records]


@router.patch("/claims/{claim_id}", response_model=ClaimDetailOut)
def update_claim(
    claim_id: uuid.UUID,
    body: ClaimUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Update a claim's text, priority, review state, or evidence state."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    update_data = body.model_dump(exclude_unset=True)

    if "review_state" in update_data:
        target_state = update_data["review_state"]
        if target_state != claim.review_state:
            old = claim.review_state
            valid = False
            if old == ReviewState.PENDING_REVIEW and target_state in (
                ReviewState.ACCEPTED, ReviewState.EDITED_AND_ACCEPTED, ReviewState.REJECTED, ReviewState.NEEDS_CLARIFICATION
            ):
                valid = True
            elif old == ReviewState.NEEDS_CLARIFICATION and target_state in (
                ReviewState.ACCEPTED, ReviewState.EDITED_AND_ACCEPTED, ReviewState.REJECTED, ReviewState.PENDING_REVIEW
            ):
                valid = True
            elif old == ReviewState.REJECTED and target_state == ReviewState.PENDING_REVIEW:
                valid = True
            elif old in (ReviewState.ACCEPTED, ReviewState.EDITED_AND_ACCEPTED) and target_state == ReviewState.PENDING_REVIEW:
                valid = True

            if not valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid state transition from {old.value} to {target_state.value}",
                )

    for field, val in update_data.items():
        setattr(claim, field, val)

    try:
        create_audit_event(
            db,
            actor_id=user.id,
            action="claim.updated",
            entity_type="claim",
            entity_id=claim.id,
            details={"updated_fields": list(update_data.keys())},
            summary=f"Updated claim: {claim.title[:60]}",
        )
        db.commit()
        db.refresh(claim)
    except Exception:
        db.rollback()
        raise

    pack = claim.transfer_pack
    case_id = pack.case_id if pack else None
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first() if case_id else None
    allow_restricted = _resolve_user_clearance(
        db, request, project_id=case.project_id if case else None, case_id=case_id
    )

    evidence_records = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == claim.id)
        .order_by(ClaimEvidence.created_at.asc())
        .all()
    )
    is_restr = any(ev.is_restricted for ev in evidence_records)
    evidence_items = [_enrich_evidence_out(ev, db, allow_restricted=allow_restricted) for ev in evidence_records]
    base_out = _project_claim_out(claim, len(evidence_items), is_restr, allow_restricted)

    return ClaimDetailOut(
        **base_out.model_dump(),
        evidence=evidence_items,
    )
