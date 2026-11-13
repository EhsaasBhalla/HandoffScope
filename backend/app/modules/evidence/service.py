"""Evidence and Claim Review service layer.

Phase 8 — Review & Approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.events import publish_case_event
from app.db.enums import Priority, QuestionStatus, ReviewState
from app.modules.audit.service import create_audit_event
from app.modules.questions.models import Question
from app.modules.transfer_packs.models import Claim


def review_claim(
    db: Session,
    *,
    claim_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    edited_body: Optional[str] = None,
    reason: Optional[str] = None,
) -> Claim:
    """Execute a claim review transition according to state machine rules.

    Valid transitions:
    - PENDING_REVIEW -> ACCEPTED, EDITED_AND_ACCEPTED, REJECTED, NEEDS_CLARIFICATION
    - NEEDS_CLARIFICATION -> ACCEPTED, EDITED_AND_ACCEPTED, REJECTED
    - REJECTED -> PENDING_REVIEW (resubmit)
    - ACCEPTED / EDITED_AND_ACCEPTED -> PENDING_REVIEW (reopen)
    """
    claim_query = db.query(Claim).filter(Claim.id == claim_id)
    try:
        if db.bind and db.bind.dialect.name != "sqlite":
            claim_query = claim_query.with_for_update()
    except Exception:
        pass
    claim = claim_query.first()
    if not claim:
        raise ValueError("Claim not found")

    act = action.lower().strip()
    now_iso = datetime.now(timezone.utc).isoformat()
    old_state = claim.review_state

    if act in {"accept", "approve"}:
        if old_state == ReviewState.ACCEPTED:
            return claim
        if old_state not in (ReviewState.PENDING_REVIEW, ReviewState.NEEDS_CLARIFICATION):
            raise ValueError(
                f"Cannot accept claim in state '{old_state.value}'. Only PENDING_REVIEW or NEEDS_CLARIFICATION claims can be accepted."
            )
        claim.review_state = ReviewState.ACCEPTED
        claim.reviewed_by = user_id
        claim.reviewed_at = now_iso
        if reason:
            claim.review_notes = reason
        audit_action = "claim.accepted"
        audit_summary = f"Accepted claim '{claim.title[:60]}'"

    elif act == "edit_and_accept":
        if old_state not in (ReviewState.PENDING_REVIEW, ReviewState.NEEDS_CLARIFICATION):
            raise ValueError(
                f"Cannot edit and accept claim in state '{old_state.value}'. Only PENDING_REVIEW or NEEDS_CLARIFICATION claims can be edited and accepted."
            )
        if not edited_body or not edited_body.strip():
            raise ValueError("edited_body must be provided for edit_and_accept")
        if not claim.original_body_text:
            claim.original_body_text = claim.body_text
        claim.body_text = edited_body.strip()
        claim.review_state = ReviewState.EDITED_AND_ACCEPTED
        claim.reviewed_by = user_id
        claim.reviewed_at = now_iso
        if reason:
            claim.review_notes = reason
        audit_action = "claim.edited_and_accepted"
        audit_summary = f"Edited and accepted claim '{claim.title[:60]}'"

    elif act == "reject":
        if old_state not in (ReviewState.PENDING_REVIEW, ReviewState.NEEDS_CLARIFICATION):
            raise ValueError(
                f"Cannot reject claim in state '{old_state.value}'. Only PENDING_REVIEW or NEEDS_CLARIFICATION claims can be rejected."
            )
        if not reason or not reason.strip():
            raise ValueError("A clear reason is required when rejecting a claim")
        claim.review_state = ReviewState.REJECTED
        claim.reviewed_by = user_id
        claim.reviewed_at = now_iso
        claim.review_notes = reason.strip()
        audit_action = "claim.rejected"
        audit_summary = f"Rejected claim '{claim.title[:60]}': {reason[:80]}"

    elif act == "needs_clarification":
        if old_state != ReviewState.PENDING_REVIEW:
            raise ValueError(
                f"Cannot request clarification on claim in state '{old_state.value}'. Only PENDING_REVIEW claims can be flagged for clarification."
            )
        if not reason or not reason.strip():
            raise ValueError("Clarification details/questions required")
        claim.review_state = ReviewState.NEEDS_CLARIFICATION
        claim.reviewed_by = user_id
        claim.reviewed_at = now_iso
        claim.review_notes = reason.strip()

        # Automatically spawn a linked handover question for this knowledge gap
        try:
            pack = claim.transfer_pack
            if pack and pack.case_id:
                new_q = Question(
                    case_id=pack.case_id,
                    transfer_pack_id=pack.id,
                    claim_id=claim.id,
                    question_text=f"Clarification needed on claim: {claim.title}",
                    why_it_matters=reason.strip(),
                    priority=Priority.HIGH,
                    status=QuestionStatus.OPEN,
                    created_by_id=user_id,
                )
                db.add(new_q)
        except Exception:
            pass

        audit_action = "claim.needs_clarification"
        audit_summary = f"Flagged claim '{claim.title[:60]}' for clarification: {reason[:80]}"

    elif act in {"resubmit", "reopen"}:
        if old_state == ReviewState.PENDING_REVIEW:
            raise ValueError("Claim is already in PENDING_REVIEW state.")
        claim.review_state = ReviewState.PENDING_REVIEW
        claim.reviewed_by = user_id
        claim.reviewed_at = now_iso
        audit_action = "claim.resubmitted"
        audit_summary = f"Resubmitted claim '{claim.title[:60]}' for review"

    else:
        raise ValueError(
            f"Unsupported review action '{action}'. Must be one of: accept, edit_and_accept, reject, needs_clarification, resubmit"
        )

    try:
        db.flush()

        create_audit_event(
            db,
            actor_id=user_id,
            action=audit_action,
            entity_type="claim",
            entity_id=claim.id,
            details={
                "old_state": old_state.value,
                "new_state": claim.review_state.value,
                "action": act,
                "reason": reason,
            },
            summary=audit_summary,
        )

        db.commit()
        db.refresh(claim)
    except Exception:
        db.rollback()
        raise
    if claim.transfer_pack and claim.transfer_pack.case_id:
        publish_case_event(
            case_id=claim.transfer_pack.case_id,
            event_type="claim.reviewed",
            entity_id=str(claim.id),
        )
    return claim
