"""Reconstruction API router.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.evidence.models import ExtractionRun
from app.modules.reconstruction import service
from app.modules.reconstruction.schemas import ExtractionRunOut, ReconstructionTriggerResponse
from app.modules.workspaces.models import User

router = APIRouter(tags=["reconstruction"])


@router.post(
    "/cases/{case_id}/reconstruct",
    response_model=ReconstructionTriggerResponse,
    status_code=status.HTTP_200_OK,
)
def trigger_reconstruction(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Trigger the knowledge reconstruction pipeline for a handover case."""
    return service.run_extraction(db, case_id, actor_id=user.id)


@router.get(
    "/cases/{case_id}/extraction-runs",
    response_model=list[ExtractionRunOut],
)
def list_case_extraction_runs(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """List historical AI extraction runs for a handover case."""
    return (
        db.query(ExtractionRun)
        .filter(ExtractionRun.case_id == case_id)
        .order_by(ExtractionRun.created_at.desc())
        .all()
    )


@router.get(
    "/extraction-runs/{run_id}",
    response_model=ExtractionRunOut,
)
def get_extraction_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Get details of a specific extraction run."""
    run = db.query(ExtractionRun).filter(ExtractionRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    return run
