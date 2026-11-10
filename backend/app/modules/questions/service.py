"""Service layer for Questions and Responses.

Phase 7 — Targeted Questions & Knowledge Gaps.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.db.enums import Priority, QuestionResponseReviewState, QuestionStatus
from app.modules.audit.service import create_audit_event
from app.modules.questions.models import Question, QuestionResponse
from app.modules.questions.schemas import (
    QuestionCreate,
    QuestionOut,
    QuestionResponseOut,
    QuestionUpdate,
)


def _to_question_out(q: Question) -> QuestionOut:
    responses = [
        QuestionResponseOut(
            id=r.id,
            question_id=r.question_id,
            respondent_id=r.respondent_id,
            respondent_name=r.respondent.display_name if r.respondent else None,
            response_text=r.response_text,
            review_state=r.review_state.value if hasattr(r.review_state, "value") else str(r.review_state),
            reviewed_by_id=r.reviewed_by_id,
            reviewed_by_name=r.reviewer.display_name if r.reviewer else None,
            reviewed_at=r.reviewed_at,
            review_notes=r.review_notes,
            created_at=r.created_at.isoformat(),
        )
        for r in q.responses
    ]
    return QuestionOut(
        id=q.id,
        case_id=q.case_id,
        case_number=q.case.case_number if q.case else None,
        case_title=q.case.title if q.case else None,
        transfer_pack_id=q.transfer_pack_id,
        transfer_pack_name=q.transfer_pack.name if q.transfer_pack else None,
        question_text=q.question_text,
        why_it_matters=q.why_it_matters,
        assigned_to_id=q.assigned_to_id,
        assigned_to_name=q.assigned_to.display_name if q.assigned_to else None,
        priority=q.priority.value if hasattr(q.priority, "value") else str(q.priority),
        status=q.status.value if hasattr(q.status, "value") else str(q.status),
        due_date=q.due_date,
        created_by_id=q.created_by_id,
        created_by_name=q.created_by.display_name if q.created_by else None,
        created_at=q.created_at.isoformat(),
        responses=responses,
    )


def list_questions(
    db: Session,
    *,
    case_id: uuid.UUID | None = None,
    status: str | None = None,
    assigned_to_id: uuid.UUID | None = None,
) -> list[QuestionOut]:
    """Query questions with optional case, status, or assignee filters."""
    query = (
        db.query(Question)
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.assigned_to),
            joinedload(Question.created_by),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .order_by(Question.created_at.desc())
    )

    if case_id:
        query = query.filter(Question.case_id == case_id)
    if assigned_to_id:
        query = query.filter(Question.assigned_to_id == assigned_to_id)
    if status and status.upper() != "ALL":
        try:
            enum_status = QuestionStatus(status.upper())
            query = query.filter(Question.status == enum_status)
        except ValueError:
            pass

    questions = query.all()
    return [_to_question_out(q) for q in questions]


def get_question(db: Session, *, question_id: uuid.UUID) -> QuestionOut:
    """Get a single question by ID with loaded relationships."""
    question = (
        db.query(Question)
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.assigned_to),
            joinedload(Question.created_by),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .filter(Question.id == question_id)
        .first()
    )
    if not question:
        raise ValueError("Question not found")
    return _to_question_out(question)


def create_question(
    db: Session,
    *,
    user_id: uuid.UUID,
    data: QuestionCreate,
) -> QuestionOut:
    """Create a new question on a handover case."""
    priority = Priority.MEDIUM
    if data.priority:
        try:
            priority = Priority(data.priority.upper())
        except ValueError:
            pass

    question = Question(
        case_id=data.case_id,
        question_text=data.question_text,
        why_it_matters=data.why_it_matters,
        transfer_pack_id=data.transfer_pack_id,
        claim_id=data.claim_id,
        assigned_to_id=data.assigned_to_id,
        priority=priority,
        status=QuestionStatus.OPEN,
        due_date=data.due_date,
        created_by_id=user_id,
    )
    db.add(question)
    db.flush()

    create_audit_event(
        db,
        actor_id=user_id,
        action="question.created",
        entity_type="question",
        entity_id=question.id,
        details={"case_id": str(data.case_id), "question": data.question_text[:100]},
        summary=f"Created question: {data.question_text[:80]}",
    )
    db.commit()
    db.refresh(question)
    return _to_question_out(question)


VALID_QUESTION_TRANSITIONS: dict[QuestionStatus, set[QuestionStatus]] = {
    QuestionStatus.DRAFT: {QuestionStatus.OPEN, QuestionStatus.CANCELLED},
    QuestionStatus.OPEN: {QuestionStatus.ANSWERED, QuestionStatus.DISMISSED, QuestionStatus.CANCELLED},
    QuestionStatus.ANSWERED: {QuestionStatus.PENDING_REVIEW, QuestionStatus.OPEN, QuestionStatus.RESOLVED},
    QuestionStatus.PENDING_REVIEW: {QuestionStatus.RESOLVED, QuestionStatus.OPEN},
    QuestionStatus.RESOLVED: {QuestionStatus.OPEN},
    QuestionStatus.DISMISSED: {QuestionStatus.OPEN},
    QuestionStatus.CANCELLED: {QuestionStatus.OPEN, QuestionStatus.DRAFT},
}


def update_question(
    db: Session,
    *,
    question_id: uuid.UUID,
    user_id: uuid.UUID,
    data: QuestionUpdate,
) -> QuestionOut:
    """Update question fields or transition question status."""
    question = (
        db.query(Question)
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.assigned_to),
            joinedload(Question.created_by),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .filter(Question.id == question_id)
        .first()
    )
    if not question:
        raise ValueError("Question not found")

    changed_fields = []

    if data.question_text is not None and data.question_text != question.question_text:
        question.question_text = data.question_text
        changed_fields.append("question_text")

    if data.why_it_matters is not None and data.why_it_matters != question.why_it_matters:
        question.why_it_matters = data.why_it_matters
        changed_fields.append("why_it_matters")

    if data.transfer_pack_id is not None and data.transfer_pack_id != question.transfer_pack_id:
        question.transfer_pack_id = data.transfer_pack_id
        changed_fields.append("transfer_pack_id")

    if data.claim_id is not None and data.claim_id != question.claim_id:
        question.claim_id = data.claim_id
        changed_fields.append("claim_id")

    if data.assigned_to_id is not None and data.assigned_to_id != question.assigned_to_id:
        question.assigned_to_id = data.assigned_to_id
        changed_fields.append("assigned_to_id")

    if data.due_date is not None and data.due_date != question.due_date:
        question.due_date = data.due_date
        changed_fields.append("due_date")

    if data.priority is not None:
        try:
            enum_priority = Priority(data.priority.upper())
            if question.priority != enum_priority:
                question.priority = enum_priority
                changed_fields.append("priority")
        except ValueError:
            pass

    if data.status is not None:
        try:
            target_status = QuestionStatus(data.status.upper())
            if target_status != question.status:
                allowed = VALID_QUESTION_TRANSITIONS.get(question.status, set())
                if target_status not in allowed:
                    raise ValueError(f"Invalid transition from {question.status.value} to {target_status.value}")
                old_status = question.status
                question.status = target_status
                changed_fields.append(f"status({old_status.value}->{target_status.value})")
        except ValueError as exc:
            raise ValueError(str(exc))

    db.flush()

    if changed_fields:
        create_audit_event(
            db,
            actor_id=user_id,
            action="question.updated",
            entity_type="question",
            entity_id=question.id,
            details={"changes": changed_fields},
            summary=f"Updated question #{question.id}: {', '.join(changed_fields)}",
        )

    db.commit()
    db.refresh(question)
    return _to_question_out(question)


def add_response(
    db: Session,
    *,
    question_id: uuid.UUID,
    user_id: uuid.UUID,
    response_text: str,
) -> QuestionOut:
    """Submit an answer to a question."""
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise ValueError("Question not found")

    response = QuestionResponse(
        question_id=question.id,
        respondent_id=user_id,
        response_text=response_text,
        review_state=QuestionResponseReviewState.PENDING_REVIEW,
    )
    db.add(response)
    question.status = QuestionStatus.ANSWERED
    db.flush()

    create_audit_event(
        db,
        actor_id=user_id,
        action="question.answered",
        entity_type="question",
        entity_id=question.id,
        details={"question_id": str(question.id)},
        summary=f"Answered question #{question.id}",
    )
    db.commit()
    db.refresh(question)
    return _to_question_out(question)


def review_response(
    db: Session,
    *,
    question_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    notes: str | None = None,
) -> QuestionOut:
    """Accept or reject the latest response to a question."""
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise ValueError("Question not found")

    if not question.responses:
        raise ValueError("No responses found for this question")

    latest_response = question.responses[-1]
    now_iso = datetime.now(timezone.utc).isoformat()

    if action.lower() == "accept":
        latest_response.review_state = QuestionResponseReviewState.ACCEPTED
        latest_response.reviewed_by_id = user_id
        latest_response.reviewed_at = now_iso
        latest_response.review_notes = notes
        question.status = QuestionStatus.RESOLVED
    elif action.lower() == "reject":
        latest_response.review_state = QuestionResponseReviewState.REJECTED
        latest_response.reviewed_by_id = user_id
        latest_response.reviewed_at = now_iso
        latest_response.review_notes = notes
        question.status = QuestionStatus.OPEN  # Re-opens question for re-answering
    elif action.lower() == "amend":
        latest_response.review_state = QuestionResponseReviewState.AMENDED
        latest_response.reviewed_by_id = user_id
        latest_response.reviewed_at = now_iso
        latest_response.review_notes = notes
        question.status = QuestionStatus.RESOLVED

    db.flush()

    create_audit_event(
        db,
        actor_id=user_id,
        action=f"question.response_{action.lower()}",
        entity_type="question",
        entity_id=question.id,
        details={"action": action, "notes": notes},
        summary=f"{action.capitalize()}ed answer for question",
    )
    db.commit()
    db.refresh(question)
    return _to_question_out(question)
