"""Service layer for Review Queue, Claim Review, and Immutable Handover Versions.

Phase 8 — Review & Approval.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_user_context_capabilities
from app.core.events import publish_case_event
from app.core.exceptions import ForbiddenError, HandoffScopeError
from app.db.enums import (
    CaseStatus,
    ClaimType,
    Priority,
    QuestionResponseReviewState,
    QuestionStatus,
    ReviewState,
    TransferPackStatus,
)
from app.modules.audit.service import create_audit_event
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import HandoverCase
from app.modules.questions.models import Question
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.schemas import ReviewBlockerOut, ReviewQueueSummaryOut
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


SNAPSHOT_SCHEMA_VERSION = 2


class SnapshotIntegrityError(HandoffScopeError):
    """Raised when an approved handover snapshot is missing, malformed, or tampered with."""


def compute_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Compute canonical SHA-256 tamper-detection hash over frozen snapshot payload."""
    core_payload = {
        "schema_version": snapshot.get("schema_version", SNAPSHOT_SCHEMA_VERSION),
        "version_number": snapshot.get("version_number"),
        "case": snapshot.get("case"),
        "transfer_packs": snapshot.get("transfer_packs", []),
        "next_actions": snapshot.get("next_actions", []),
        "unfinished_items": snapshot.get("unfinished_items", []),
        "override_metadata": snapshot.get("override_metadata"),
    }
    encoded = json.dumps(core_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_canonical_snapshot_dict(
    db: Session,
    *,
    case: HandoverCase,
    version_number: int,
    approved_at: datetime,
    approved_by_id: Optional[uuid.UUID],
    approved_by_name: Optional[str],
    amendment_reason: Optional[str] = None,
    override_metadata: Optional[dict[str, Any]] = None,
    overridden_unresolved_items: Optional[list[dict[str, Any]]] = None,
) -> tuple[dict[str, Any], list[TransferPack], int]:
    """Assemble and validate a complete, canonical frozen snapshot for a HandoverVersion."""
    packs = (
        db.query(TransferPack)
        .filter(TransferPack.case_id == case.id)
        .order_by(TransferPack.sort_order.asc(), TransferPack.created_at.asc())
        .all()
    )

    pack_payloads: list[dict[str, Any]] = []
    next_actions_snapshot: list[dict[str, Any]] = []
    unfinished_snapshot: list[dict[str, Any]] = []
    total_claims = 0

    for p in packs:
        claims = (
            db.query(Claim)
            .filter(Claim.transfer_pack_id == p.id)
            .order_by(Claim.created_at.asc())
            .all()
        )
        total_claims += len(claims)

        claim_payloads: list[dict[str, Any]] = []
        for c in claims:
            evidence_records = (
                db.query(ClaimEvidence)
                .filter(ClaimEvidence.claim_id == c.id)
                .order_by(ClaimEvidence.created_at.asc())
                .all()
            )
            evidence_payloads = [
                {
                    "id": str(ev.id),
                    "evidence_type": ev.evidence_type.value if hasattr(ev.evidence_type, "value") else str(ev.evidence_type),
                    "excerpt": ev.excerpt,
                    "locator": ev.locator,
                    "is_restricted": bool(ev.is_restricted),
                    "source_record_id": str(ev.source_record_id) if ev.source_record_id else None,
                    "document_id": str(ev.document_id) if ev.document_id else None,
                }
                for ev in evidence_records
            ]

            claim_type_val = c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type)
            prio_val = c.priority.value if hasattr(c.priority, "value") else (str(c.priority) if c.priority else "MEDIUM")
            claim_dict = {
                "id": str(c.id),
                "transfer_pack_id": str(p.id),
                "claim_type": claim_type_val,
                "title": c.title,
                "body_text": c.body_text,
                "original_body_text": c.original_body_text,
                "evidence_state": c.evidence_state.value if hasattr(c.evidence_state, "value") else str(c.evidence_state),
                "freshness": c.freshness.value if hasattr(c.freshness, "value") else str(c.freshness),
                "review_state": c.review_state.value if hasattr(c.review_state, "value") else str(c.review_state),
                "priority": prio_val,
                "reviewed_by": str(c.reviewed_by) if c.reviewed_by else None,
                "reviewed_at": c.reviewed_at,
                "review_notes": c.review_notes,
                "evidence": evidence_payloads,
            }
            claim_payloads.append(claim_dict)

            if c.claim_type == ClaimType.NEXT_ACTION:
                next_actions_snapshot.append(claim_dict)
            if c.claim_type in (ClaimType.KNOWLEDGE_GAP, ClaimType.RISK):
                unfinished_snapshot.append({
                    "id": str(c.id),
                    "type": "CLAIM",
                    "title": c.title,
                    "description": c.body_text,
                    "pack_name": p.name,
                    "priority": prio_val,
                    "is_restricted": any(ev.is_restricted for ev in evidence_records),
                })

        pack_payloads.append(
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "scope_summary": p.scope_summary,
                "component_area": p.component_area,
                "status": TransferPackStatus.APPROVED.value,
                "recorded_owner_id": str(p.recorded_owner_id) if p.recorded_owner_id else None,
                "suggested_successor_id": str(p.suggested_successor_id) if p.suggested_successor_id else None,
                "claims_count": len(claim_payloads),
                "claims": claim_payloads,
            }
        )

    if overridden_unresolved_items:
        unfinished_snapshot.extend(overridden_unresolved_items)

    snapshot: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "version_number": version_number,
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
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "approved_at": approved_at.isoformat(),
            "approved_by_id": str(approved_by_id) if approved_by_id else None,
            "approved_by_name": approved_by_name,
            "amendment_reason": amendment_reason,
            "total_packs": len(pack_payloads),
            "total_claims": total_claims,
        },
        "transfer_packs": pack_payloads,
        "next_actions": next_actions_snapshot,
        "unfinished_items": unfinished_snapshot,
    }
    if override_metadata:
        snapshot["override_metadata"] = override_metadata

    snapshot["metadata"]["snapshot_hash"] = compute_snapshot_hash(snapshot)
    return snapshot, packs, total_claims


CRITICAL_BLOCKER_TERMS = (
    "security",
    "credential",
    "password",
    "secret",
    "token",
    "kms",
    "encryption",
    "private key",
    "access exposure",
    "unauthorized",
    "data loss",
    "data-loss",
    "corruption",
    "migration",
    "production deploy",
    "production failure",
    "outage",
    "incident",
    "ownership uncertainty",
    "root access",
)


def _is_critical_text(text: str | None) -> bool:
    low = (text or "").lower()
    return any(term in low for term in CRITICAL_BLOCKER_TERMS)


def get_review_queue_summary(
    db: Session,
    *,
    case_id: uuid.UUID,
    user: User | None = None,
) -> ReviewQueueSummaryOut:
    """Authoritative preflight evaluator for review readiness, blockers, and override eligibility."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError("Handover Case not found")

    packs = db.query(TransferPack).filter(TransferPack.case_id == case_id).all()
    pack_ids = [p.id for p in packs]
    claims = db.query(Claim).filter(Claim.transfer_pack_id.in_(pack_ids)).all() if pack_ids else []
    restricted_claim_ids = {
        ce.claim_id
        for ce in (
            db.query(ClaimEvidence.claim_id)
            .filter(ClaimEvidence.claim_id.in_([c.id for c in claims]), ClaimEvidence.is_restricted.is_(True))
            .all()
        )
    } if claims else set()

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

    blockers: list[ReviewBlockerOut] = []

    if case.status == CaseStatus.CANCELLED:
        blockers.append(
            ReviewBlockerOut(
                code="CASE_CANCELLED",
                category="case",
                severity="critical",
                message="Handover Case is cancelled.",
                related_object_id=str(case.id),
                related_object_type="case",
                overridable=False,
            )
        )

    if case.is_blocked:
        reason_text = (case.blocked_reason or "").strip()
        is_crit_block = not reason_text or _is_critical_text(reason_text)
        blockers.append(
            ReviewBlockerOut(
                code="CASE_BLOCKED",
                category="security" if is_crit_block else "case",
                severity="critical" if is_crit_block else "non_critical",
                message=f"Handover Case is blocked: {reason_text or 'No block reason specified.'}",
                related_object_id=str(case.id),
                related_object_type="case",
                overridable=not is_crit_block,
                required_permission=None if is_crit_block else "case.approve_override",
            )
        )

    if not packs:
        blockers.append(
            ReviewBlockerOut(
                code="NO_PACKS",
                category="structure",
                severity="critical",
                message="No Transfer Packs exist in this handover case.",
                related_object_id=str(case.id),
                related_object_type="case",
                overridable=False,
            )
        )

    if not claims:
        blockers.append(
            ReviewBlockerOut(
                code="NO_CLAIMS",
                category="structure",
                severity="critical",
                message="No grounded claims have been generated or added.",
                related_object_id=str(case.id),
                related_object_type="case",
                overridable=False,
            )
        )

    if pending_count > 0:
        blockers.append(
            ReviewBlockerOut(
                code="PENDING_CLAIMS",
                category="claims",
                severity="critical",
                message=f"{pending_count} claim(s) are still pending review.",
                overridable=False,
            )
        )

    if rejected_count > 0:
        blockers.append(
            ReviewBlockerOut(
                code="REJECTED_CLAIMS",
                category="claims",
                severity="critical",
                message=f"{rejected_count} unresolved rejected claim(s) must be resubmitted or removed.",
                overridable=False,
            )
        )

    if clarification_count > 0:
        blockers.append(
            ReviewBlockerOut(
                code="CLARIFICATION_CLAIMS",
                category="claims",
                severity="critical",
                message=f"{clarification_count} claim(s) require knowledge clarification.",
                overridable=False,
            )
        )

    packs_needing_evidence = [p for p in packs if p.status == TransferPackStatus.NEEDS_EVIDENCE]
    if packs_needing_evidence:
        blockers.append(
            ReviewBlockerOut(
                code="PACKS_NEEDS_EVIDENCE",
                category="claims",
                severity="critical",
                message=f"{len(packs_needing_evidence)} Transfer Pack(s) are blocked awaiting grounded evidence.",
                overridable=False,
            )
        )

    # Evaluate active unresolved questions (OPEN, ANSWERED awaiting review, PENDING_REVIEW)
    active_questions = (
        db.query(Question)
        .options(joinedload(Question.responses))
        .filter(
            Question.case_id == case_id,
            Question.status.in_([QuestionStatus.OPEN, QuestionStatus.ANSWERED, QuestionStatus.PENDING_REVIEW]),
        )
        .order_by(Question.created_at.asc())
        .all()
    )

    open_q_count = 0
    awaiting_q_count = 0
    critical_q_count = 0

    for q in active_questions:
        responses = list(q.responses or [])
        latest_resp = responses[-1] if responses else None
        is_accepted_on_stale_status = (
            q.status == QuestionStatus.ANSWERED
            and latest_resp is not None
            and latest_resp.review_state == QuestionResponseReviewState.ACCEPTED
        )
        if is_accepted_on_stale_status:
            # Answered & accepted response is already resolved at response level
            continue

        is_rejected_unreplaced = (
            latest_resp is not None and latest_resp.review_state == QuestionResponseReviewState.REJECTED
        )
        is_awaiting_review = q.status in (QuestionStatus.ANSWERED, QuestionStatus.PENDING_REVIEW) or (
            latest_resp is not None and latest_resp.review_state == QuestionResponseReviewState.PENDING_REVIEW
        )

        is_crit_q = (
            q.priority == Priority.CRITICAL
            or _is_critical_text(f"{q.question_text} {q.why_it_matters or ''}")
        )
        if is_crit_q:
            critical_q_count += 1
        if is_awaiting_review:
            awaiting_q_count += 1
        else:
            open_q_count += 1

        # Protect restricted claim context in blocker messages
        if q.claim_id and q.claim_id in restricted_claim_ids:
            q_label = f"Question #{str(q.id)[:8]} (linked to restricted item)"
        else:
            q_label = f"'{q.question_text[:72]}{'...' if len(q.question_text) > 72 else ''}'"

        if is_awaiting_review:
            code = "CRITICAL_AWAITING_REVIEW" if is_crit_q else "AWAITING_ANSWER_REVIEW"
            msg = f"Question {q_label} has an AI or human draft answer awaiting reviewer acceptance."
        elif is_rejected_unreplaced:
            code = "CRITICAL_REJECTED_ANSWER" if is_crit_q else "REJECTED_QUESTION_ANSWER"
            msg = f"Question {q_label} has a rejected answer awaiting replacement."
        else:
            code = "CRITICAL_OPEN_QUESTION" if is_crit_q else "OPEN_QUESTION"
            msg = f"{'Critical ' if is_crit_q else ''}Open question remains unresolved: {q_label}"

        blockers.append(
            ReviewBlockerOut(
                code=code,
                category="security" if is_crit_q else "questions",
                severity="critical" if is_crit_q else "non_critical",
                message=msg,
                related_object_id=str(q.id),
                related_object_type="question",
                overridable=not is_crit_q,
                required_permission=None if is_crit_q else "case.approve_override",
            )
        )

    blocking_reasons = [b.message for b in blockers]
    has_critical_blockers = any(not b.overridable or b.severity == "critical" for b in blockers)
    can_approve = len(blockers) == 0

    user_has_override_perm = False
    if user is not None:
        caps, _, _ = get_user_context_capabilities(db, user, case_id=case_id)
        user_has_override_perm = "case.approve_override" in caps

    can_override = (
        not can_approve
        and len(blockers) > 0
        and not has_critical_blockers
        and user_has_override_perm
    )

    return ReviewQueueSummaryOut(
        case_id=case.id,
        case_number=case.case_number,
        case_title=case.title,
        case_status=case.status.value if hasattr(case.status, "value") else str(case.status),
        can_approve=can_approve,
        blocking_reasons=blocking_reasons,
        blockers=blockers,
        has_critical_blockers=has_critical_blockers,
        can_override=can_override,
        is_blocked=bool(case.is_blocked),
        blocked_reason=case.blocked_reason,
        total_claims=len(claims),
        pending_review_count=pending_count,
        accepted_count=accepted_count,
        edited_and_accepted_count=edited_count,
        rejected_count=rejected_count,
        needs_clarification_count=clarification_count,
        open_questions_count=open_q_count,
        awaiting_question_review_count=awaiting_q_count,
        critical_questions_count=critical_q_count,
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
    override_blockers: bool = False,
    override_reason: Optional[str] = None,
) -> HandoverVersion:
    """Create an immutable snapshot version and transition the case to APPROVED.

    Enforces single authoritative preflight inside the transaction:
    - Ordinary approval requires zero blockers and 'case.approve'.
    - Lead override requires 'case.approve_override', zero critical blockers,
      and a meaningful override_reason (>= 10 chars). Critical blockers never override.
    """
    case_query = db.query(HandoverCase).filter(HandoverCase.id == case_id)
    try:
        if db.bind and db.bind.dialect.name != "sqlite":
            case_query = case_query.with_for_update()
    except Exception:
        pass
    case = case_query.first()
    if not case:
        raise ValueError("Handover Case not found")

    approver = db.query(User).filter(User.id == user_id).first()
    if not approver:
        raise ForbiddenError("Approving user not found")

    caps, _, _ = get_user_context_capabilities(db, approver, case_id=case_id)
    if "case.approve" not in caps:
        raise ForbiddenError("User does not have permission to approve handover versions for this case.")

    summary = get_review_queue_summary(db, case_id=case_id, user=approver)
    override_metadata: dict[str, Any] | None = None
    overridden_unfinished: list[dict[str, Any]] = []

    if not summary.can_approve:
        if not override_blockers:
            raise ValueError(f"Approval blocked: {'; '.join(summary.blocking_reasons)}")

        if "case.approve_override" not in caps:
            raise ForbiddenError("Only an authorized Project Lead or Workspace Owner may override approval blockers.")

        critical_reasons = [b.message for b in summary.blockers if not b.overridable or b.severity == "critical"]
        if critical_reasons:
            raise ValueError(
                f"Cannot override critical approval blocker(s): {'; '.join(critical_reasons)}"
            )

        cleaned_reason = (override_reason or "").strip()
        if len(cleaned_reason) < 10:
            raise ValueError("Override requires a meaningful justification of at least 10 characters.")

        now_iso = datetime.now(timezone.utc).isoformat()
        overridden_list = [b.model_dump() for b in summary.blockers]
        override_metadata = {
            "overridden": True,
            "overridden_by_id": str(user_id),
            "overridden_by_name": approver.display_name,
            "override_reason": cleaned_reason,
            "overridden_at": now_iso,
            "overridden_blockers": overridden_list,
        }
        for b in summary.blockers:
            overridden_unfinished.append({
                "id": b.related_object_id or b.code,
                "type": f"OVERRIDDEN_{b.category.upper()}",
                "title": b.message,
                "description": f"Approved with Lead override ({approver.display_name}): {cleaned_reason}",
                "pack_name": "Governance Override",
                "priority": "MEDIUM",
            })

    # Determine sequential version number
    prev_version = (
        db.query(HandoverVersion)
        .filter(HandoverVersion.case_id == case_id)
        .order_by(HandoverVersion.version_number.desc())
        .first()
    )
    new_version_number = (prev_version.version_number + 1) if prev_version else 1
    previous_version_id = prev_version.id if prev_version else None

    now_dt = datetime.now(timezone.utc)
    snapshot, packs, total_claims = build_canonical_snapshot_dict(
        db,
        case=case,
        version_number=new_version_number,
        approved_at=now_dt,
        approved_by_id=user_id,
        approved_by_name=approver.display_name if approver else None,
        amendment_reason=amendment_reason,
        override_metadata=override_metadata,
        overridden_unresolved_items=overridden_unfinished or None,
    )

    if not snapshot.get("transfer_packs"):
        raise SnapshotIntegrityError("Cannot seal version without frozen transfer_packs snapshot payload.")

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

    # Transition case and packs status to APPROVED (do NOT clear case.is_blocked or mark questions resolved)
    case.status = CaseStatus.APPROVED
    for p in packs:
        p.status = TransferPackStatus.APPROVED

    db.flush()

    create_audit_event(
        db,
        actor_id=user_id,
        action="case.approved_with_override" if override_metadata else "case.approved",
        entity_type="handover_version",
        entity_id=version.id,
        details={
            "case_id": str(case_id),
            "version_number": new_version_number,
            "total_packs": len(packs),
            "total_claims": total_claims,
            "amendment_reason": amendment_reason,
            "snapshot_hash": snapshot["metadata"]["snapshot_hash"],
            "override_metadata": override_metadata,
        },
        summary=(
            f"Approved handover version v{new_version_number} for case #{case.case_number} WITH LEAD OVERRIDE"
            if override_metadata
            else f"Approved immutable handover version v{new_version_number} for case #{case.case_number}"
        ),
    )

    db.commit()
    db.refresh(version)

    # Index the newly frozen immutable snapshot for conversational RAG (non-blocking if embedder fails)
    try:
        from app.modules.rag.indexing import index_approved_version_chunks

        index_approved_version_chunks(db, case_id=case_id, version_id=version.id)
        db.commit()
    except Exception:
        db.rollback()

    publish_case_event(
        case_id=case_id,
        event_type="version.approved",
        entity_id=str(version.id),
    )
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
