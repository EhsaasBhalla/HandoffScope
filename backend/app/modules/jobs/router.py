"""Job API router — job status and progress endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.jobs.models import Job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


class JobResponse(BaseModel):
    id: uuid.UUID
    job_type: str
    status: str
    progress_current: int
    progress_total: int
    progress_message: str | None = None
    error_message: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None

    model_config = {"from_attributes": True}


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Get job status and progress."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobResponse(
        id=job.id,
        job_type=job.job_type.value,
        status=job.status.value,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        progress_message=job.progress_message,
        error_message=job.error_message,
        entity_type=job.entity_type,
        entity_id=job.entity_id,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )
