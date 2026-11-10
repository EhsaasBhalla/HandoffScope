"""Service layer for Review Queue, Claim Review, and Immutable Handover Versions.

Phase 8 — Review & Approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.db.enums import CaseStatus, ReviewState, TransferPackStatus
from app.modules.audit.service import create_audit_event
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import HandoverCase
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.schemas import ReviewQueueSummaryOut
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


def get_review_queue_summary(db: Session, *, case_id: uuid.UUID) -> ReviewQueueSummaryOut:
    """Analyze the review status of all claims and packs for a handover case."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError("Handover Case not found")

    packs = db.query(TransferPack).filter(TransferPack.case_id == case_id).all()
    pack_ids = [p.id for p in packs]

    claims = db.query(Claim).filter(Claim.transfer_pack_id.in_(pack_ids)).all() if pack_ids else []

    pending_count = sum(1 for c in claims if c.review_state == ReviewState.PENDING_REVIEW)
    accepted_count = sum(1 for c in claims if c.review_state == ReviewState.ACCEPTED)
    edited_count = sum(1 for c in claims if c.review_state == ReviewState.EDITED_AND_ACCEPTED)
    rejected_count = sum(1 for c in claims if c.review_state == ReviewState.REJECTED)
    clarification_count = sum(1 for c in claims if c.review_state == ReviewState.NEEDS_CLARIFICATION)
    approved_packs = sum(1 for p in packs if p.status == TransferPackStatus.APPROVED)

    versions = (
        db.query(HandoverVersion)
        .filter(HandoverVersion.case_id == case_id)
        .order_by(HandoverVersion.version_number.desc())
        .all()
    )
    current_version = next((v.version_number for v in versions if v.is_current), None)

    blocking_reasons: list[str] = []

    if case.status == CaseStatus.CANCELLED:
        blocking_reasons.append("Handover Case is cancelled.")

    if not packs:
        blocking_reasons.append("No Transfer Packs exist in this handover case.")

    if not claims:
        blocking_reasons.append("No grounded claims have been generated or added.")

    if pending_count > 0:
        blocking_reasons.append(f"{pending_count} claim(s) are still pending review.")

    if rejected_count > 0:
        blocking_reasons.append(f"{rejected_count} unresolved rejected claim(s) must be resubmitted or removed.")

    if clarification_count > 0:
        blocking_reasons.append(f"{clarification_count} claim(s) require knowledge clarification.")

    # Check packs needing evidence
    packs_needing_evidence = [p for p in packs if p.status == TransferPackStatus.NEEDS_EVIDENCE]
    if packs_needing_evidence:
        blocking_reasons.append(f"{len(packs_needing_evidence)} Transfer Pack(s) are blocked awaiting grounded evidence.")

    can_approve = len(blocking_reasons) == 0

    return ReviewQueueSummaryOut(
        case_id=case.id,
        case_number=case.case_number,
        case_title=case.title,
        case_status=case.status.value if hasattr(case.status, "value") else str(case.status),
        can_approve=can_approve,
        blocking_reasons=blocking_reasons,
        total_claims=len(claims),
        pending_review_count=pending_count,
        accepted_count=accepted_count,
        edited_and_accepted_count=edited_count,
        rejected_count=rejected_count,
        needs_clarification_count=clarification_count,
        total_packs=len(packs),
        approved_packs_count=approved_packs,
        versions_count=len(versions),
        current_version_number=current_version,
    )


def create_approved_version(
    db: Session,
    *,
    case_id: uuid.UUID,
    user_id: uuid.UUID,
    amendment_reason: Optional[str] = None,
) -> HandoverVersion:
    """Create an immutable snapshot version and transition the case to APPROVED.

    Preconditions enforced:
    - Case exists and is not cancelled
    - No unresolved rejected claims
    - No claims needing clarification
    - No unreviewed claims
    - At least 1 pack and 1 claim exist
    """
    summary = get_review_queue_summary(db, case_id=case_id)
    if not summary.can_approve:
        raise ValueError(f"Approval blocked: {'; '.join(summary.blocking_reasons)}")

    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    approver = db.query(User).filter(User.id == user_id).first()

    # Determine sequential version number
    prev_version = (
        db.query(HandoverVersion)
        .filter(HandoverVersion.case_id == case_id)
        .order_by(HandoverVersion.version_number.desc())
        .first()
    )
    new_version_number = (prev_version.version_number + 1) if prev_version else 1
    previous_version_id = prev_version.id if prev_version else None

    # Fetch all packs, claims, and evidence
    packs = (
        db.query(TransferPack)
        .filter(TransferPack.case_id == case_id)
        .order_by(TransferPack.sort_order.asc(), TransferPack.created_at.asc())
        .all()
    )

    pack_payloads = []
    total_claims = 0
    now_dt = datetime.now(timezone.utc)

    for p in packs:
        claims = (
            db.query(Claim)
            .filter(Claim.transfer_pack_id == p.id)
            .order_by(Claim.created_at.asc())
            .all()
        )
        total_claims += len(claims)

        claim_payloads = []
        for c in claims:
            evidence_records = (
                db.query(ClaimEvidence)
                .filter(ClaimEvidence.claim_id == c.id)
                .all()
            )
            evidence_payloads = [
                {
                    "id": str(ev.id),
                    "evidence_type": ev.evidence_type.value if hasattr(ev.evidence_type, "value") else str(ev.evidence_type),
                    "excerpt": ev.excerpt,
                    "locator": ev.locator,
                    "is_restricted": ev.is_restricted,
                    "source_record_id": str(ev.source_record_id) if ev.source_record_id else None,
                    "document_id": str(ev.document_id) if ev.document_id else None,
                }
                for ev in evidence_records
            ]

            claim_payloads.append(
                {
                    "id": str(c.id),
                    "claim_type": c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type),
                    "title": c.title,
                    "body_text": c.body_text,
                    "original_body_text": c.original_body_text,
                    "evidence_state": c.evidence_state.value if hasattr(c.evidence_state, "value") else str(c.evidence_state),
                    "freshness": c.freshness.value if hasattr(c.freshness, "value") else str(c.freshness),
                    "review_state": c.review_state.value if hasattr(c.review_state, "value") else str(c.review_state),
                    "priority": c.priority.value if hasattr(c.priority, "value") else (str(c.priority) if c.priority else None),
                    "reviewed_by": str(c.reviewed_by) if c.reviewed_by else None,
                    "reviewed_at": c.reviewed_at,
                    "review_notes": c.review_notes,
                    "evidence": evidence_payloads,
                }
            )

        pack_payloads.append(
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "scope_summary": p.scope_summary,
                "component_area": p.component_area,
                "recorded_owner_id": str(p.recorded_owner_id) if p.recorded_owner_id else None,
                "suggested_successor_id": str(p.suggested_successor_id) if p.suggested_successor_id else None,
                "claims": claim_payloads,
            }
        )

    # Build frozen immutable snapshot
    snapshot = {
        "version_number": new_version_number,
        "case": {
            "id": str(case.id),
            "case_number": case.case_number,
            "title": case.title,
            "project_id": str(case.project_id),
            "created_by_id": str(case.created_by_id) if case.created_by_id else None,
            "scope_start": case.scope_start.isoformat() if case.scope_start else None,
            "scope_end": case.scope_end.isoformat() if case.scope_end else None,
        },
        "metadata": {
            "approved_at": now_dt.isoformat(),
            "approved_by_id": str(user_id),
            "approved_by_name": approver.display_name if approver else None,
            "amendment_reason": amendment_reason,
            "total_packs": len(pack_payloads),
            "total_claims": total_claims,
        },
        "transfer_packs": pack_payloads,
    }

    # Mark prior versions is_current = False
    db.query(HandoverVersion).filter(HandoverVersion.case_id == case_id).update({"is_current": False})

    version = HandoverVersion(
        id=uuid.uuid4(),
        case_id=case_id,
        version_number=new_version_number,
        approved_by_id=user_id,
        approved_at=now_dt,
        snapshot_json=snapshot,
        is_current=True,
        amendment_reason=amendment_reason,
        previous_version_id=previous_version_id,
    )
    db.add(version)

    # Transition case and packs status to APPROVED
    case.status = CaseStatus.APPROVED
    for p in packs:
        p.status = TransferPackStatus.APPROVED

    db.flush()

    create_audit_event(
        db,
        actor_id=user_id,
        action="case.approved",
        entity_type="handover_version",
        entity_id=version.id,
        details={
            "case_id": str(case_id),
            "version_number": new_version_number,
            "total_packs": len(pack_payloads),
            "total_claims": total_claims,
            "amendment_reason": amendment_reason,
        },
        summary=f"Approved immutable handover version v{new_version_number} for case #{case.case_number}",
    )

    db.commit()
    db.refresh(version)
    return version


def list_case_versions(db: Session, *, case_id: uuid.UUID) -> list[HandoverVersion]:
    """List all version records for a handover case, ordered sequentially."""
    return (
        db.query(HandoverVersion)
        .options(joinedload(HandoverVersion.approver))
        .filter(HandoverVersion.case_id == case_id)
        .order_by(HandoverVersion.version_number.desc())
        .all()
    )


def get_version_detail(db: Session, *, version_id: uuid.UUID) -> HandoverVersion:
    """Retrieve full details of an immutable version including frozen snapshot."""
    version = (
        db.query(HandoverVersion)
        .options(joinedload(HandoverVersion.approver))
        .filter(HandoverVersion.id == version_id)
        .first()
    )
    if not version:
        raise ValueError("Handover Version not found")
    return version
