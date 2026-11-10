"""Sources API router — connect, list, import, manage sources."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.db.enums import ConnectionStatus, JobType, SourceType
from app.modules.sources.models import ConnectedSource, SyncRun
from app.modules.jobs.service import enqueue_job
from app.modules.audit.service import create_audit_event

router = APIRouter(tags=["Sources"])


class SourceResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_type: str
    name: str
    external_id: str | None = None
    connection_status: str
    created_at: str

    model_config = {"from_attributes": True}


class SourceConnectRequest(BaseModel):
    source_type: str
    name: str
    external_id: str | None = None
    config: dict | None = None


class SyncRunResponse(BaseModel):
    id: uuid.UUID
    status: str
    records_fetched: int
    records_created: int
    records_updated: int
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    model_config = {"from_attributes": True}


@router.get("/projects/{project_id}/sources", response_model=list[SourceResponse])
def list_sources(
    project_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List connected sources for a project."""
    sources = (
        db.query(ConnectedSource)
        .filter(ConnectedSource.project_id == project_id)
        .order_by(ConnectedSource.created_at.desc())
        .all()
    )
    return [SourceResponse(
        id=s.id,
        project_id=s.project_id,
        source_type=s.source_type.value,
        name=s.name,
        external_id=s.external_id,
        connection_status=s.connection_status.value,
        created_at=s.created_at.isoformat(),
    ) for s in sources]


@router.post("/projects/{project_id}/sources", response_model=SourceResponse, status_code=201)
def connect_source(
    project_id: uuid.UUID,
    body: SourceConnectRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Connect a new source to a project."""
    try:
        source_type = SourceType(body.source_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown source type: {body.source_type}")

    # Check for duplicate
    existing = (
        db.query(ConnectedSource)
        .filter(
            ConnectedSource.project_id == project_id,
            ConnectedSource.source_type == source_type,
            ConnectedSource.external_id == body.external_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Source already connected")

    source = ConnectedSource(
        project_id=project_id,
        source_type=source_type,
        name=body.name,
        external_id=body.external_id,
        connection_status=ConnectionStatus.ACTIVE,
        config=body.config,
        connected_by_id=user.id,
    )
    db.add(source)
    db.flush()

    create_audit_event(
        db,
        actor_id=user.id,
        action="source.connected",
        entity_type="connected_source",
        entity_id=source.id,
        details={"source_type": body.source_type, "name": body.name},
        summary=f"Connected source: {body.name}",
    )
    db.commit()
    db.refresh(source)

    return SourceResponse(
        id=source.id,
        project_id=source.project_id,
        source_type=source.source_type.value,
        name=source.name,
        external_id=source.external_id,
        connection_status=source.connection_status.value,
        created_at=source.created_at.isoformat(),
    )


@router.post("/sources/{source_id}/import", status_code=202)
def trigger_import(
    source_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Trigger a background import job for a source."""
    source = db.query(ConnectedSource).filter(ConnectedSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    job = enqueue_job(
        db,
        job_type=JobType.SOURCE_IMPORT,
        entity_type="connected_source",
        entity_id=source_id,
        created_by_id=user.id,
        params={"source_id": str(source_id)},
        idempotency_key=f"import-{source_id}",
        queue_name="handoffscope-import",
        task_func="app.workers.import_task.run_import",
    )
    db.commit()

    return {"message": "Import job enqueued", "job_id": str(job.id)}


@router.get("/sources/{source_id}/sync-runs", response_model=list[SyncRunResponse])
def list_sync_runs(
    source_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List sync runs for a source."""
    runs = (
        db.query(SyncRun)
        .filter(SyncRun.source_id == source_id)
        .order_by(SyncRun.created_at.desc())
        .limit(20)
        .all()
    )
    return [SyncRunResponse(
        id=r.id,
        status=r.status.value,
        records_fetched=r.records_fetched,
        records_created=r.records_created,
        records_updated=r.records_updated,
        error_message=r.error_message,
        started_at=r.started_at.isoformat() if r.started_at else None,
        completed_at=r.completed_at.isoformat() if r.completed_at else None,
    ) for r in runs]
