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
from app.modules.reconstruction.schemas import (
    ExtractionRunOut,
    ReconstructionTriggerResponse,
    RegenerateDecisionsResponse,
)
from app.modules.workspaces.models import User

router = APIRouter(tags=["reconstruction"])


def _to_extraction_run_out(run: ExtractionRun) -> ExtractionRunOut:
    meta = (run.validated_output_json or {}).get("_provider_meta") or {}
    default_mode = "mock" if "mock" in (run.model_name or "").lower() else "live"
    return ExtractionRunOut(
        id=run.id,
        case_id=run.case_id,
        model_name=run.model_name,
        status=run.status,
        prompt_template_version=run.prompt_template_version,
        token_usage_input=run.token_usage_input,
        token_usage_output=run.token_usage_output,
        latency_ms=run.latency_ms,
        error_message=run.error_message,
        provider_mode=meta.get("provider_mode") or default_mode,
        fallback_used=bool(meta.get("fallback_used", False)),
        fallback_reason=meta.get("fallback_reason"),
        context_stats=meta.get("context_stats"),
        created_at=run.created_at,
    )


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
    try:
        return service.run_extraction(db, case_id, actor_id=user.id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/cases/{case_id}/regenerate-decisions",
    response_model=RegenerateDecisionsResponse,
    status_code=status.HTTP_200_OK,
)
def regenerate_case_decisions_endpoint(
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Regenerate and update authoritative architectural and technical decisions for a handover case."""
    try:
        return service.regenerate_case_decisions(db, case_id=case_id, actor_id=user.id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


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
    runs = (
        db.query(ExtractionRun)
        .filter(ExtractionRun.case_id == case_id)
        .order_by(ExtractionRun.created_at.desc())
        .all()
    )
    return [_to_extraction_run_out(r) for r in runs]


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
    return _to_extraction_run_out(run)
