"""Sources API router — connect, list, import, manage sources."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.credentials import encrypt_source_config, sanitize_source_config_for_api
from app.core.dependencies import (
    get_current_active_user,
    get_db,
    require_case_capability,
    require_project_capability,
)
from app.db.enums import ConnectionStatus, JobStatus, JobType, Sensitivity, SourceType, SyncRunStatus
from app.modules.audit.service import create_audit_event
from app.modules.jobs.models import Job
from app.modules.jobs.service import enqueue_job
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource, SyncRun
from app.modules.sources.schemas import (
    RefreshRequest,
    SourceConnectRequest,
    SourceRecordDetailOut,
    SourceResponse,
    SyncRunResponse,
)

router = APIRouter(tags=["Sources"])

# Re-export for backward compatibility
__all__ = [
    "SyncRunResponse",
    "SourceResponse",
    "SourceConnectRequest",
    "RefreshRequest",
    "SourceRecordDetailOut",
    "router",
]


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
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
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
    """List connected sources for a project (project membership required)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    require_project_capability(db, user, project_id, "source.view")

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
                source_type=s.source_type.value if hasattr(s.source_type, "value") else str(s.source_type),
                name=s.name,
                external_id=s.external_id,
                connection_status=s.connection_status.value if hasattr(s.connection_status, "value") else str(s.connection_status),
                config=sanitize_source_config_for_api(s.config),
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
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    require_project_capability(db, user, project_id, "source.connect")

    try:
        source_type = SourceType(body.source_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown source type: {body.source_type}")

    config_data = dict(body.config) if body.config else {}
    normalized_external_id = body.external_id

    if source_type == SourceType.GITHUB_REPO and (not config_data.get("owner") or not config_data.get("repo")):
        from app.modules.sources.url_parser import parse_github_repo_identifier

        raw_ref = body.external_id or body.name or ""
        try:
            parsed = parse_github_repo_identifier(raw_ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if parsed:
            owner, repo, canonical_url = parsed
            config_data["owner"] = owner
            config_data["repo"] = repo
            config_data.setdefault("url", canonical_url)
            if not normalized_external_id or "github.com" in normalized_external_id.lower():
                normalized_external_id = f"{owner}/{repo}"
    elif source_type == SourceType.GITLAB_REPO:
        proj_path = (config_data.get("project_path") or normalized_external_id or body.name or "").strip().strip("/")
        if proj_path.startswith("https://gitlab.com/"):
            proj_path = proj_path.replace("https://gitlab.com/", "").rstrip(".git").strip("/")
        if "/" not in proj_path:
            raise HTTPException(status_code=400, detail="GitLab source requires 'namespace/project' path")
        config_data["project_path"] = proj_path
        config_data.setdefault("base_url", "https://gitlab.com")
        normalized_external_id = normalized_external_id or proj_path
    elif source_type == SourceType.LINEAR_TEAM:
        team_key = (config_data.get("team_key") or normalized_external_id or "").strip().upper()
        token = (config_data.get("access_token") or config_data.get("api_token") or "").strip()
        if not team_key or not token:
            raise HTTPException(status_code=400, detail="Linear source requires team_key and API key / OAuth token")
        config_data["team_key"] = team_key
        normalized_external_id = normalized_external_id or team_key
    elif source_type == SourceType.JIRA_PROJECT:
        site_url = (config_data.get("site_url") or "").strip().rstrip("/")
        proj_key = (config_data.get("project_key") or normalized_external_id or "").strip().upper()
        email = (config_data.get("email") or "").strip()
        api_token = (config_data.get("api_token") or "").strip()
        if not site_url.startswith("https://") or not proj_key or not email or not api_token:
            raise HTTPException(
                status_code=400,
                detail="Jira source requires https:// site_url, project_key, email, and api_token",
            )
        config_data["site_url"] = site_url
        config_data["project_key"] = proj_key
        normalized_external_id = normalized_external_id or f"{site_url}/{proj_key}"

    # Check for duplicate with normalized external ID
    existing = (
        db.query(ConnectedSource)
        .filter(
            ConnectedSource.project_id == project_id,
            ConnectedSource.source_type == source_type,
            ConnectedSource.external_id == normalized_external_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Source already connected")

    encrypted_config = encrypt_source_config(config_data)

    source = ConnectedSource(
        project_id=project_id,
        source_type=source_type,
        name=body.name,
        external_id=normalized_external_id,
        connection_status=ConnectionStatus.ACTIVE,
        config=encrypted_config,
        connected_by_id=user.id,
    )
    try:
        db.add(source)
        db.flush()

        create_audit_event(
            db,
            actor_id=user.id,
            action="source.connected",
            entity_type="connected_source",
            entity_id=source.id,
            details={"source_type": body.source_type, "name": body.name, "external_id": normalized_external_id},
            summary=f"Connected source: {body.name}",
        )
        db.commit()
        db.refresh(source)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source already connected to this project",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return SourceResponse(
        id=source.id,
        project_id=source.project_id,
        source_type=source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type),
        name=source.name,
        external_id=source.external_id,
        connection_status=source.connection_status.value if hasattr(source.connection_status, "value") else str(source.connection_status),
        config=sanitize_source_config_for_api(source.config),
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
    require_project_capability(db, user, source.project_id, "source.import")

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

    try:
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
    except Exception:
        db.rollback()
        raise

    return {"message": "Import job enqueued", "job_id": str(job.id)}


@router.get("/sources/{source_id}/sync-runs", response_model=list[SyncRunResponse])
def list_sync_runs(
    source_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List sync runs for a source."""
    source = db.query(ConnectedSource).filter(ConnectedSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    require_project_capability(db, user, source.project_id, "source.view")

    runs = (
        db.query(SyncRun)
        .filter(SyncRun.source_id == source_id)
        .order_by(SyncRun.created_at.desc())
        .limit(20)
        .all()
    )
    return [_build_sync_run_response(db, r) for r in runs]


@router.post("/sources/{source_id}/refresh")
def refresh_source_endpoint(
    source_id: uuid.UUID,
    body: RefreshRequest | None = None,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Manually refresh a source and propagate staleness."""
    from app.modules.sources.service import refresh_source

    source = db.query(ConnectedSource).filter(ConnectedSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    require_project_capability(db, user, source.project_id, "source.import")

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

    require_case_capability(db, user, case_id, "source.import")
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


@router.get("/cases/{case_id}/sources/records/{record_id}", response_model=SourceRecordDetailOut)
def get_case_source_record(
    case_id: uuid.UUID,
    record_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve a permitted source record belonging to a case for citation drilldown."""
    from app.modules.evidence.clearance import has_restricted_clearance, resolve_case_source_ids
    from app.modules.handover_cases.models import HandoverCase
    from app.modules.ingestion.models import SourceRecord

    require_case_capability(db, user, case_id, "case.view")
    case_obj = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case_obj:
        raise HTTPException(status_code=404, detail="Case not found")

    record = db.query(SourceRecord).filter(SourceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Source record not found")

    # Verify record belongs strictly to this case's connected sources / project
    allowed_src_ids = set(
        resolve_case_source_ids(db, case_id=case_id, project_id=case_obj.project_id)
    )
    if record.connected_source_id not in allowed_src_ids:
        raise HTTPException(status_code=404, detail="Source record does not belong to this case")

    # Enforce RESTRICTED sensitivity guard without leaking title/body/url
    if record.sensitivity == Sensitivity.RESTRICTED:
        if not has_restricted_clearance(
            db,
            user_id=user.id,
            project_id=case_obj.project_id,
            case_id=case_id,
            user=user,
        ):
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
