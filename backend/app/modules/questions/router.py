"""API router for Questions & Responses."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.questions.schemas import (
    QuestionCreate,
    QuestionOut,
    QuestionResponseCreate,
    QuestionReviewRequest,
)
from app.modules.questions.service import (
    add_response,
    create_question,
    list_questions,
    review_response,
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
    return list_questions(db, case_id=case_id, status=status)


@router.post("/cases/{case_id}/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
def post_case_question(
    case_id: uuid.UUID,
    body: QuestionCreate,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new question for a handover case."""
    body.case_id = case_id
    return create_question(db, user_id=user.id, data=body)


@router.post("/questions/{question_id}/responses", response_model=QuestionOut)
def submit_question_response(
    question_id: uuid.UUID,
    body: QuestionResponseCreate,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Submit an answer to an open question."""
    try:
        return add_response(db, question_id=question_id, user_id=user.id, response_text=body.response_text)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/questions/{question_id}/review", response_model=QuestionOut)
def review_question_response(
    question_id: uuid.UUID,
    body: QuestionReviewRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Review (accept or reject) an answer to a question."""
    try:
        return review_response(db, question_id=question_id, user_id=user.id, action=body.action, notes=body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
