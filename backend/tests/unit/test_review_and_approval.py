"""Unit tests for Phase 8: Claim review actions, review preconditions, and immutable versions."""

import uuid
import pytest
from app.db.enums import CaseStatus, ClaimType, EvidenceState, Freshness, ReviewState, TransferPackStatus, TransitionType
from app.db.session import SessionLocal
from app.modules.evidence.service import review_claim
from app.modules.handover_cases.models import HandoverCase
from app.modules.questions.models import Question
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.service import (
    create_approved_version,
    get_review_queue_summary,
    get_version_detail,
    list_case_versions,
)
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_claim_review_actions_and_preservation(db):
    user = db.query(User).filter(User.email == "maya.sharma@example.test").first()
    assert user is not None
    pack = db.query(TransferPack).first()
    assert pack is not None

    # 1. Create a fresh claim
    claim = Claim(
        id=uuid.uuid4(),
        transfer_pack_id=pack.id,
        claim_type=ClaimType.DECISION,
        title="Deploy to multiple AWS availability zones",
        body_text="Original text: Infrastructure must span us-east-1a and us-east-1b.",
        evidence_state=EvidenceState.SUPPORTED,
        freshness=Freshness.CURRENT,
        review_state=ReviewState.PENDING_REVIEW,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    claim_id = claim.id

    # 2. Reject without reason should fail
    with pytest.raises(ValueError, match="reason is required"):
        review_claim(db, claim_id=claim_id, user_id=user.id, action="reject", reason="")

    # 3. Reject with reason
    rejected = review_claim(
        db,
        claim_id=claim_id,
        user_id=user.id,
        action="reject",
        reason="Does not comply with single-region multi-AZ budget guidelines.",
    )
    assert rejected.review_state == ReviewState.REJECTED
    assert rejected.review_notes == "Does not comply with single-region multi-AZ budget guidelines."
    assert rejected.reviewed_by == user.id

    # 4. Resubmit for review
    resubmitted = review_claim(db, claim_id=claim_id, user_id=user.id, action="resubmit")
    assert resubmitted.review_state == ReviewState.PENDING_REVIEW

    # 5. Needs clarification (should auto-create a Question)
    initial_q_count = db.query(Question).filter(Question.claim_id == claim_id).count()
    clarification_claim = review_claim(
        db,
        claim_id=claim_id,
        user_id=user.id,
        action="needs_clarification",
        reason="Which subnets are configured for the database instances?",
    )
    assert clarification_claim.review_state == ReviewState.NEEDS_CLARIFICATION
    new_q_count = db.query(Question).filter(Question.claim_id == claim_id).count()
    assert new_q_count >= initial_q_count + 1

    # 6. Edit and Accept (preserves original body text)
    edited_text = "Modified text: Infrastructure spans us-east-1a and us-east-1b with private subnets 10.0.1.0/24."
    accepted = review_claim(
        db,
        claim_id=claim_id,
        user_id=user.id,
        action="edit_and_accept",
        edited_body=edited_text,
        reason="Updated with specific subnet CIDR blocks.",
    )
    assert accepted.review_state == ReviewState.EDITED_AND_ACCEPTED
    assert accepted.body_text == edited_text
    assert accepted.original_body_text == "Original text: Infrastructure must span us-east-1a and us-east-1b."
    assert accepted.reviewed_by == user.id


def test_version_preconditions_and_immutability(db):
    user = db.query(User).filter(User.email == "maya.sharma@example.test").first()
    assert user is not None

    project_id = (db.query(TransferPack).first()).case.project_id
    from sqlalchemy import func
    max_num = db.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == project_id).scalar() or 0
    next_case_num = max_num + 1

    # Create an isolated test case
    test_case = HandoverCase(
        id=uuid.uuid4(),
        case_number=next_case_num,
        title=f"Version Approval Test Case #{next_case_num}",
        transition_type=TransitionType.PLANNED_DEPARTURE,
        status=CaseStatus.UNDER_REVIEW,
        project_id=project_id,
        created_by_id=user.id,
    )
    db.add(test_case)
    db.flush()

    pack = TransferPack(
        id=uuid.uuid4(),
        case_id=test_case.id,
        name="Review Test Pack",
        status=TransferPackStatus.READY_FOR_REVIEW,
    )
    db.add(pack)
    db.flush()

    c1 = Claim(
        id=uuid.uuid4(),
        transfer_pack_id=pack.id,
        claim_type=ClaimType.WORK_ITEM,
        title="Complete runbook documentation",
        body_text="All steps documented.",
        review_state=ReviewState.PENDING_REVIEW,
    )
    db.add(c1)
    db.commit()

    # 1. Approval should fail because c1 is PENDING_REVIEW
    summary = get_review_queue_summary(db, case_id=test_case.id)
    assert not summary.can_approve
    assert any("pending review" in r for r in summary.blocking_reasons)

    with pytest.raises(ValueError, match="Approval blocked"):
        create_approved_version(db, case_id=test_case.id, user_id=user.id)

    # 2. Reject c1 -> Approval should fail because unresolved rejection
    review_claim(db, claim_id=c1.id, user_id=user.id, action="reject", reason="Incomplete")
    summary = get_review_queue_summary(db, case_id=test_case.id)
    assert not summary.can_approve
    assert any("rejected claim" in r for r in summary.blocking_reasons)

    # 3. Accept c1 -> All preconditions met
    review_claim(db, claim_id=c1.id, user_id=user.id, action="resubmit")
    review_claim(db, claim_id=c1.id, user_id=user.id, action="accept")

    summary = get_review_queue_summary(db, case_id=test_case.id)
    assert summary.can_approve

    # 4. Create approved version v1
    v1 = create_approved_version(db, case_id=test_case.id, user_id=user.id)
    assert v1.version_number == 1
    assert v1.is_current
    assert test_case.status == CaseStatus.APPROVED
    assert pack.status == TransferPackStatus.APPROVED

    v1_snapshot = v1.snapshot_json
    assert v1_snapshot["version_number"] == 1
    assert len(v1_snapshot["transfer_packs"]) == 1
    assert v1_snapshot["transfer_packs"][0]["claims"][0]["title"] == "Complete runbook documentation"

    # 5. Subsequent edit to claim should NOT alter v1 snapshot (Immutability guarantee)
    c1.title = "Altered title after v1 approval"
    db.commit()

    reloaded_v1 = get_version_detail(db, version_id=v1.id)
    assert reloaded_v1.snapshot_json["transfer_packs"][0]["claims"][0]["title"] == "Complete runbook documentation"

    # 6. Create v2 amendment
    review_claim(db, claim_id=c1.id, user_id=user.id, action="resubmit")
    review_claim(db, claim_id=c1.id, user_id=user.id, action="accept")
    v2 = create_approved_version(
        db,
        case_id=test_case.id,
        user_id=user.id,
        amendment_reason="Updated claim title with latest runbook links.",
    )
    assert v2.version_number == 2
    assert v2.is_current
    assert v2.previous_version_id == v1.id

    db.refresh(v1)
    assert not v1.is_current  # Previous version is no longer current
