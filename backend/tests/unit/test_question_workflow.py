"""Unit tests for Question workflow and state transitions."""

import uuid
import pytest
from app.db.enums import Priority, QuestionResponseReviewState, QuestionStatus
from app.db.session import SessionLocal
from app.modules.handover_cases.models import HandoverCase
from app.modules.questions.models import Question, QuestionResponse
from app.modules.questions.schemas import QuestionCreate, QuestionUpdate
from app.modules.questions.service import (
    add_response,
    create_question,
    get_question,
    list_questions,
    review_response,
    update_question,
)
from app.modules.workspaces.models import User


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_question_lifecycle_and_review(db):
    user = db.query(User).filter(User.email == "maya.sharma@example.test").first()
    assert user is not None
    case = db.query(HandoverCase).first()
    assert case is not None

    # 1. Create Question
    q_create = QuestionCreate(
        case_id=case.id,
        question_text="What is the backup rotation schedule for PostgreSQL backups?",
        why_it_matters="Critical for zero-loss recovery in incident response.",
        priority="HIGH",
    )
    q_out = create_question(db, user_id=user.id, data=q_create)
    assert q_out.status == "OPEN"
    assert q_out.priority == "HIGH"
    q_id = q_out.id

    # 2. Update Question
    q_update = QuestionUpdate(
        priority="CRITICAL",
        why_it_matters="Updated urgency: required before on-call handoff.",
    )
    updated_q = update_question(db, question_id=q_id, user_id=user.id, data=q_update)
    assert updated_q.priority == "CRITICAL"
    assert "on-call" in updated_q.why_it_matters

    # 3. Add Response (Transition to ANSWERED)
    answered_q = add_response(
        db,
        question_id=q_id,
        user_id=user.id,
        response_text="Backups run daily at 02:00 UTC via pg_dump and sync to S3 bucket s3://prod-backups-archive.",
    )
    assert answered_q.status == "ANSWERED"
    assert len(answered_q.responses) == 1
    assert answered_q.responses[0].review_state == "PENDING_REVIEW"

    # 4. Review Response - Reject (Requests revision, transitions back to OPEN)
    reopened_q = review_response(
        db,
        question_id=q_id,
        user_id=user.id,
        action="reject",
        notes="Please specify the retention policy and encryption keys used.",
    )
    assert reopened_q.status == "OPEN"
    assert reopened_q.responses[0].review_state == "REJECTED"

    # 5. Add Second Response
    re_answered_q = add_response(
        db,
        question_id=q_id,
        user_id=user.id,
        response_text="Retention is 30 days lifecycle rule; encrypted with AWS KMS key alias/backup-key.",
    )
    assert re_answered_q.status == "ANSWERED"
    assert len(re_answered_q.responses) == 2

    # 6. Review Response - Accept (Transitions to RESOLVED)
    resolved_q = review_response(
        db,
        question_id=q_id,
        user_id=user.id,
        action="accept",
        notes="All details verified against terraform state.",
    )
    assert resolved_q.status == "RESOLVED"
    assert resolved_q.responses[1].review_state == "ACCEPTED"

    # 7. Reopen question
    reopen_update = QuestionUpdate(status="OPEN")
    reopened_again = update_question(db, question_id=q_id, user_id=user.id, data=reopen_update)
    assert reopened_again.status == "OPEN"

    # 8. Dismiss question
    dismiss_update = QuestionUpdate(status="DISMISSED")
    dismissed_q = update_question(db, question_id=q_id, user_id=user.id, data=dismiss_update)
    assert dismissed_q.status == "DISMISSED"
