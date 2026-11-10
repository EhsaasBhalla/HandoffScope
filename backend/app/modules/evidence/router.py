"""Evidence and claims API router.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.db.enums import ClaimType, EvidenceState, ReviewState
from app.modules.documents.models import Document
from app.modules.evidence.models import ClaimEvidence
from app.modules.evidence.schemas import ClaimDetailOut, ClaimEvidenceOut, ClaimOut
from app.modules.ingestion.models import SourceRecord
from app.modules.transfer_packs.models import Claim, TransferPack

router = APIRouter(tags=["evidence"])


def _enrich_evidence_out(ev: ClaimEvidence, db: Session) -> ClaimEvidenceOut:
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

    return ClaimEvidenceOut(
        id=ev.id,
        claim_id=ev.claim_id,
        source_record_id=ev.source_record_id,
        document_id=ev.document_id,
        excerpt=ev.excerpt,
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


@router.get("/transfer-packs/{pack_id}/claims", response_model=list[ClaimOut])
def list_pack_claims(
    pack_id: uuid.UUID,
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

    result = []
    for c in claims:
        ev_count = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == c.id).count()
        result.append(
            ClaimOut(
                id=c.id,
                transfer_pack_id=c.transfer_pack_id,
                claim_type=c.claim_type,
                title=c.title,
                body_text=c.body_text,
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
        )
    return result


@router.get("/claims/{claim_id}", response_model=ClaimDetailOut)
def get_claim_detail(
    claim_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Retrieve full details of a claim including all grounded evidence references."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

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


@router.get("/claims/{claim_id}/evidence", response_model=list[ClaimEvidenceOut])
def list_claim_evidence(
    claim_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all evidence references for a specific claim."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    evidence_records = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == claim.id)
        .order_by(ClaimEvidence.created_at.asc())
        .all()
    )

    return [_enrich_evidence_out(ev, db) for ev in evidence_records]
