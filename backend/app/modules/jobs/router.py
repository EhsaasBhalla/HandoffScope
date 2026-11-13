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

    # Verify authorization: creator, project/case member, or workspace member
    if job.created_by_id and job.created_by_id != user.id:
        if job.entity_type == "handover_case" and job.entity_id:
            from app.modules.handover_cases.models import CaseParticipant, HandoverCase
            from app.modules.projects.models import ProjectMembership
            case = db.query(HandoverCase).filter(HandoverCase.id == job.entity_id).first()
            if case:
                is_participant = (
                    db.query(CaseParticipant)
                    .filter(CaseParticipant.case_id == case.id, CaseParticipant.user_id == user.id)
                    .first()
                    is not None
                )
                is_proj_member = (
                    db.query(ProjectMembership)
                    .filter(ProjectMembership.project_id == case.project_id, ProjectMembership.user_id == user.id)
                    .first()
                    is not None
                )
                if not (is_participant or is_proj_member):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this job")
        elif job.entity_type == "project" and job.entity_id:
            from app.modules.projects.models import ProjectMembership
            is_proj_member = (
                db.query(ProjectMembership)
                .filter(ProjectMembership.project_id == job.entity_id, ProjectMembership.user_id == user.id)
                .first()
                is not None
            )
            if not is_proj_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this job")

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
