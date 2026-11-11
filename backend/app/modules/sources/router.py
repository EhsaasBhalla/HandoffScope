"""Sources API router — connect, list, import, manage sources."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db, get_user_context_capabilities, require_case_capability
from app.db.enums import CaseParticipantRole, ConnectionStatus, JobStatus, JobType, Sensitivity, SourceType, SyncRunStatus
from app.modules.jobs.models import Job
from app.modules.sources.models import ConnectedSource, SyncRun
from app.modules.jobs.service import enqueue_job
from app.modules.audit.service import create_audit_event

router = APIRouter(tags=["Sources"])


class SyncRunResponse(BaseModel):
    id: uuid.UUID
    status: str
    records_fetched: int
    records_created: int
    records_updated: int
    records_skipped: int = 0
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    model_config = {"from_attributes": True}


class SourceResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_type: str
    name: str
    external_id: str | None = None
    connection_status: str
    created_at: str
    updated_at: str | None = None
    last_successful_sync_at: str | None = None
    last_sync_run: SyncRunResponse | None = None

    model_config = {"from_attributes": True}


class SourceConnectRequest(BaseModel):
    source_type: str
    name: str
    external_id: str | None = None
    config: dict | None = None


def _build_sync_run_response(db: Session, run: SyncRun) -> SyncRunResponse:
    skipped = 0
    matching_job = (
        db.query(Job)
        .filter(
            Job.entity_id == run.source_id,
            Job.job_type == JobType.SOURCE_IMPORT,
        )
        .order_by(Job.created_at.desc())
        .limit(10)
        .all()
    )
    for j in matching_job:
        res = j.result or {}
        if res.get("sync_run_id") == str(run.id) and "records_skipped" in res:
            skipped = int(res["records_skipped"] or 0)
            break
    return SyncRunResponse(
        id=run.id,
        status=run.status.value,
        records_fetched=run.records_fetched,
        records_created=run.records_created,
        records_updated=run.records_updated,
        records_skipped=skipped,
        error_message=run.error_message,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


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
    out: list[SourceResponse] = []
    for s in sources:
        latest_run = (
            db.query(SyncRun)
            .filter(SyncRun.source_id == s.id)
            .order_by(SyncRun.created_at.desc())
            .first()
        )
        last_ok = (
            db.query(SyncRun)
            .filter(SyncRun.source_id == s.id, SyncRun.status == SyncRunStatus.COMPLETED)
            .order_by(SyncRun.completed_at.desc())
            .first()
        )
        last_ok_ts = last_ok.completed_at or last_ok.created_at if last_ok else None
        out.append(
            SourceResponse(
                id=s.id,
                project_id=s.project_id,
                source_type=s.source_type.value,
                name=s.name,
                external_id=s.external_id,
                connection_status=s.connection_status.value,
                created_at=s.created_at.isoformat(),
                updated_at=s.updated_at.isoformat() if s.updated_at else None,
                last_successful_sync_at=last_ok_ts.isoformat() if last_ok_ts else None,
                last_sync_run=_build_sync_run_response(db, latest_run) if latest_run else None,
            )
        )
    return out


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

    config_data = dict(body.config) if body.config else {}
    if source_type == SourceType.GITHUB_REPO and (not config_data.get("owner") or not config_data.get("repo")):
        slug = (body.external_id or body.name or "").strip().strip("/")
        if slug.startswith("https://github.com/"):
            slug = slug.replace("https://github.com/", "").rstrip(".git").strip("/")
        if "/" in slug:
            parts = slug.split("/")
            config_data["owner"] = parts[0].strip()
            config_data["repo"] = parts[1].strip()

    source = ConnectedSource(
        project_id=project_id,
        source_type=source_type,
        name=body.name,
        external_id=body.external_id,
        connection_status=ConnectionStatus.ACTIVE,
        config=config_data or None,
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

    # Avoid double-triggering if a sync is currently pending or running
    active_job = (
        db.query(Job)
        .filter(
            Job.entity_id == source_id,
            Job.job_type == JobType.SOURCE_IMPORT,
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .first()
    )
    if active_job:
        return {"message": "Import job already in progress", "job_id": str(active_job.id)}

    job = enqueue_job(
        db,
        job_type=JobType.SOURCE_IMPORT,
        entity_type="connected_source",
        entity_id=source_id,
        created_by_id=user.id,
        params={"source_id": str(source_id)},
        idempotency_key=f"import-{source_id}-{uuid.uuid4().hex[:12]}",
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
    return [_build_sync_run_response(db, r) for r in runs]


class RefreshRequest(BaseModel):
    simulate_modification: bool = False


@router.post("/sources/{source_id}/refresh")
def refresh_source_endpoint(
    source_id: uuid.UUID,
    body: RefreshRequest | None = None,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Manually refresh a source and propagate staleness."""
    from app.modules.sources.service import refresh_source
    simulate = body.simulate_modification if body else False
    try:
        return refresh_source(
            db,
            source_id=source_id,
            actor_id=user.id,
            simulate_modification=simulate,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/cases/{case_id}/refresh-sources")
def refresh_case_sources_endpoint(
    case_id: uuid.UUID,
    body: RefreshRequest | None = None,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Manually refresh all connected sources for a handover case and propagate staleness."""
    from app.modules.sources.service import refresh_case_sources
    simulate = body.simulate_modification if body else False
    try:
        return refresh_case_sources(
            db,
            case_id=case_id,
            actor_id=user.id,
            simulate_modification=simulate,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class SourceRecordDetailOut(BaseModel):
    id: uuid.UUID
    record_type: str
    external_id: str
    title: str | None = None
    body: str | None = None
    author_name: str | None = None
    state: str | None = None
    url: str | None = None
    sensitivity: str
    external_created_at: str | None = None
    metadata_json: dict | None = None


@router.get("/cases/{case_id}/sources/records/{record_id}", response_model=SourceRecordDetailOut)
def get_case_source_record(
    case_id: uuid.UUID,
    record_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve a permitted source record belonging to a case for citation drilldown."""
    from app.modules.handover_cases.models import CaseParticipant, CaseSource, HandoverCase
    from app.modules.ingestion.models import SourceRecord

    require_case_capability(db, user, case_id, "case.view")
    case_obj = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case_obj:
        raise HTTPException(status_code=404, detail="Case not found")

    record = db.query(SourceRecord).filter(SourceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Source record not found")

    # Verify record belongs strictly to this case's connected sources / project
    case_sources = db.query(CaseSource).filter(CaseSource.case_id == case_id).all()
    if case_sources:
        allowed_src_ids = {cs.connected_source_id for cs in case_sources}
    else:
        allowed_src_ids = {
            s.id for s in db.query(ConnectedSource).filter(ConnectedSource.project_id == case_obj.project_id).all()
        }
    if record.connected_source_id not in allowed_src_ids:
        raise HTTPException(status_code=404, detail="Source record does not belong to this case")

    # Enforce RESTRICTED sensitivity guard without leaking title/body/url
    if record.sensitivity == Sensitivity.RESTRICTED:
        _, ws_roles, proj_roles = get_user_context_capabilities(db, user, case_id=case_id)
        is_recipient = (
            db.query(CaseParticipant)
            .filter(
                CaseParticipant.case_id == case_id,
                CaseParticipant.user_id == user.id,
                CaseParticipant.role == CaseParticipantRole.RECIPIENT,
            )
            .first()
            is not None
        )
        is_lead = ("OWNER" in ws_roles or proj_roles.get(str(case_obj.project_id)) == "LEAD") and not is_recipient
        if not is_lead:
            raise HTTPException(status_code=403, detail="Access to restricted source record requires elevated clearance")

    return SourceRecordDetailOut(
        id=record.id,
        record_type=record.record_type.value if hasattr(record.record_type, "value") else str(record.record_type),
        external_id=record.external_id,
        title=record.title,
        body=record.body,
        author_name=record.author_name or record.author_external_id,
        state=record.state,
        url=record.url,
        sensitivity=record.sensitivity.value if hasattr(record.sensitivity, "value") else str(record.sensitivity),
        external_created_at=record.external_created_at.isoformat() if record.external_created_at else None,
        metadata_json=record.metadata_json,
    )

