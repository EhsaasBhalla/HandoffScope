"""API router for Questions & Responses."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db, require_case_capability
from app.modules.questions.models import Question, QuestionResponse
from app.modules.questions.schemas import (
    QuestionCreate,
    QuestionOut,
    QuestionResponseCreate,
    QuestionReviewRequest,
    QuestionUpdate,
)
from app.modules.questions.service import (
    add_response,
    create_question,
    generate_ai_answer,
    get_question,
    list_questions,
    review_response,
    update_question,
)

router = APIRouter(tags=["Questions"])


@router.get("/questions", response_model=list[QuestionOut])
def get_all_questions(
    case_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List questions across the workspace or filtered by case/status."""
    return list_questions(db, case_id=case_id, status=status)


@router.get("/cases/{case_id}/questions", response_model=list[QuestionOut])
def get_case_questions(
    case_id: uuid.UUID,
    status: Optional[str] = Query(None),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List questions belonging to a specific handover case."""
    require_case_capability(db, user, case_id, "question.view")
    return list_questions(db, case_id=case_id, status=status)


@router.post("/cases/{case_id}/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
def post_case_question(
    case_id: uuid.UUID,
    body: QuestionCreate,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new question for a handover case."""
    require_case_capability(db, user, case_id, "question.create")
    body.case_id = case_id
    try:
        return create_question(db, user_id=user.id, data=body)
    except Exception:
        db.rollback()
        raise


@router.post("/questions/{question_id}/generate-answer", response_model=QuestionOut)
def generate_ai_question_answer(
    question_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Generate an evidence-grounded AI draft answer (PENDING_REVIEW) for a question."""
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    require_case_capability(db, user, q.case_id, "question.generate_ai")
    try:
        return generate_ai_answer(db, question_id=question_id, user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.post("/questions/{question_id}/responses", response_model=QuestionOut)
def submit_question_response(
    question_id: uuid.UUID,
    body: QuestionResponseCreate,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Submit an answer to an open question."""
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    require_case_capability(db, user, q.case_id, "question.answer")
    try:
        return add_response(
            db,
            question_id=question_id,
            user_id=user.id,
            response_text=body.response_text,
            attachments=body.attachments,
            evidence_references=body.evidence_references,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.patch("/questions/{question_id}/review", response_model=QuestionOut)
def review_question_response(
    question_id: uuid.UUID,
    body: QuestionReviewRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Review (accept, reject, or amend) an answer to a question."""
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    require_case_capability(db, user, q.case_id, "question.review")
    try:
        return review_response(
            db,
            question_id=question_id,
            user_id=user.id,
            action=body.action,
            notes=body.notes,
            amended_text=body.amended_text,
            attachments=body.attachments,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.get("/questions/{question_id}", response_model=QuestionOut)
def get_single_question(
    question_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve full details of a specific question."""
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    require_case_capability(db, user, q.case_id, "question.view")
    return get_question(db, question_id=question_id)


@router.patch("/questions/{question_id}", response_model=QuestionOut)
def patch_question(
    question_id: uuid.UUID,
    body: QuestionUpdate,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update question attributes or transition question status."""
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    require_case_capability(db, user, q.case_id, "question.view")
    try:
        return update_question(db, question_id=question_id, user_id=user.id, data=body)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.patch("/question-responses/{response_id}/review", response_model=QuestionOut)
def review_response_direct(
    response_id: uuid.UUID,
    body: QuestionReviewRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Review a response directly by response ID."""
    resp = db.query(QuestionResponse).filter(QuestionResponse.id == response_id).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Question response not found")
    q = db.query(Question).filter(Question.id == resp.question_id).first()
    if q:
        require_case_capability(db, user, q.case_id, "question.review")
    try:
        return review_response(
            db,
            question_id=resp.question_id,
            user_id=user.id,
            action=body.action,
            notes=body.notes,
            response_id=response_id,
            amended_text=body.amended_text,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        db.rollback()
        raise
