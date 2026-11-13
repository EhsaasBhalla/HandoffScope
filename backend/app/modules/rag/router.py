"""API router for Conversational RAG ("Ask the Handover")."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.core.exceptions import ForbiddenError, HandoffScopeError
from app.modules.workspaces.models import User

from app.modules.rag.schemas import (
    RagAskRequest,
    RagAskResponse,
    RagReindexRequest,
    RagReindexResultOut,
    RagThreadDetailOut,
    RagThreadOut,
)
from app.modules.rag.service import (
    ask_handover_question,
    get_thread_detail,
    list_case_threads,
    reindex_case_rag,
)

router = APIRouter(tags=["Handover Assistant (RAG)"])


@router.get("/cases/{case_id}/chat/threads", response_model=list[RagThreadOut])
def list_rag_threads(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List current user's RAG conversation threads for a handover case."""
    try:
        return list_case_threads(db, case_id=case_id, user=user)
    except ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/cases/{case_id}/chat/threads/{thread_id}", response_model=RagThreadDetailOut)
def get_rag_thread_detail(
    case_id: uuid.UUID,
    thread_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve message history and citations for a pinned RAG conversation thread."""
    try:
        return get_thread_detail(db, case_id=case_id, thread_id=thread_id, user=user)
    except ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/cases/{case_id}/chat/ask", response_model=RagAskResponse)
def ask_rag_endpoint(
    case_id: uuid.UUID,
    body: RagAskRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Ask a natural-language question grounded strictly in version-pinned, clearance-filtered evidence."""
    try:
        return ask_handover_question(db, case_id=case_id, user=user, body=body)
    except ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HandoffScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/cases/{case_id}/chat/reindex", response_model=RagReindexResultOut)
def reindex_rag_endpoint(
    case_id: uuid.UUID,
    body: RagReindexRequest | None = None,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Explicitly rebuild/refresh knowledge chunks for an approved version or draft case."""
    req = body or RagReindexRequest()
    try:
        return reindex_case_rag(
            db,
            case_id=case_id,
            user=user,
            context_mode=req.context_mode,
            version_id=req.version_id,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
