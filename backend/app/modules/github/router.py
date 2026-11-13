"""GitHub module — signed OAuth state, encrypted tokens, HMAC webhook verification, and ETag polling."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.credentials import decrypt_secret, encrypt_secret
from app.core.dependencies import get_current_active_user, get_db, require_project_capability
from app.db.enums import JobStatus, JobType, SourceType
from app.modules.audit.service import create_audit_event
from app.modules.jobs.models import Job
from app.modules.jobs.service import enqueue_job
from app.modules.sources.models import ConnectedSource, GitHubInstallation
from app.modules.workspaces.models import WorkspaceMembership

logger = logging.getLogger("handoffscope.github")

router = APIRouter(prefix="/github", tags=["GitHub"])


class GitHubStatusResponse(BaseModel):
    connected: bool
    installation_id: int | None = None
    account_login: str | None = None


class GitHubInstallUrlResponse(BaseModel):
    url: str


def _sign_oauth_state(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "typ": "github_oauth_state",
        "sub": str(user_id),
        "nonce": secrets.token_urlsafe(12),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _verify_oauth_state(state_token: str | None) -> uuid.UUID:
    if not state_token:
        raise HTTPException(status_code=400, detail="Missing OAuth state token")
    try:
        payload = jwt.decode(state_token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("typ") != "github_oauth_state":
            raise HTTPException(status_code=400, detail="Invalid OAuth state type")
        return uuid.UUID(str(payload["sub"]))
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state parameter") from exc


@router.get("/install-url", response_model=GitHubInstallUrlResponse)
def get_install_url(user=Depends(get_current_active_user)):
    """Return the GitHub App installation URL with cryptographically signed state."""
    if not settings.GITHUB_APP_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App not configured. Public repositories sync directly without an App.",
        )
    signed_state = _sign_oauth_state(user.id)
    url = f"https://github.com/apps/handoffscope/installations/new?state={signed_state}"
    return GitHubInstallUrlResponse(url=url)


@router.get("/callback")
async def github_callback(
    code: str = Query(...),
    installation_id: int = Query(...),
    setup_action: str = Query("install"),
    state: str = Query(None),
    db: Session = Depends(get_db),
):
    """Handle GitHub App OAuth callback with signed state validation and encrypted token storage."""
    from app.integrations.github.client import exchange_code_for_token, get_installation_token

    if not settings.GITHUB_APP_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub App not configured")

    user_id = _verify_oauth_state(state)

    token_data = await exchange_code_for_token(code)
    if "error" in token_data:
        raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth error"))

    install_token_data = await get_installation_token(installation_id)

    ws_membership = db.query(WorkspaceMembership).filter(
        WorkspaceMembership.user_id == user_id
    ).first()
    if not ws_membership:
        raise HTTPException(status_code=400, detail="Could not determine workspace for user")
    workspace_id = ws_membership.workspace_id

    encrypted_install_token = encrypt_secret(install_token_data.get("token"))
    existing = db.query(GitHubInstallation).filter(
        GitHubInstallation.installation_id == installation_id
    ).first()

    if existing:
        existing.access_token = encrypted_install_token
        existing.token_expires_at = install_token_data.get("expires_at")
    else:
        installation = GitHubInstallation(
            workspace_id=workspace_id,
            installation_id=installation_id,
            account_login=token_data.get("login", "unknown"),
            account_type="Organization",
            access_token=encrypted_install_token,
            installed_by_id=user_id,
        )
        db.add(installation)

    create_audit_event(
        db,
        actor_id=user_id,
        action="github.app_installed",
        entity_type="workspace",
        entity_id=workspace_id,
        details={"installation_id": installation_id, "setup_action": setup_action},
        summary=f"Connected GitHub App installation #{installation_id}",
    )
    db.commit()
    return {"message": "GitHub App installed successfully", "installation_id": installation_id}


@router.get("/status", response_model=GitHubStatusResponse)
def get_github_status(
    workspace_id: uuid.UUID = Query(...),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Check GitHub App connection status for a workspace."""
    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.workspace_id == workspace_id
    ).first()

    if not installation:
        return GitHubStatusResponse(connected=False)

    return GitHubStatusResponse(
        connected=True,
        installation_id=installation.installation_id,
        account_login=installation.account_login,
    )


@router.post("/webhook", status_code=202)
async def github_webhook_receiver(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default="ping"),
    x_github_delivery: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Verify HMAC-SHA256 webhook signature, deduplicate delivery ID, and enqueue incremental sync."""
    secret = (settings.GITHUB_APP_WEBHOOK_SECRET or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GITHUB_APP_WEBHOOK_SECRET is not configured",
        )

    raw_body = await request.body()
    expected_sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected_sig, x_hub_signature_256.strip()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    event_name = (x_github_event or "").lower()
    if event_name == "ping":
        return {"status": "ok", "event": "ping"}

    if event_name not in ("push", "issues", "pull_request", "repository"):
        return {"status": "ignored", "event": event_name}

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed webhook JSON payload") from exc

    repo_full_name = ((payload.get("repository") or {}).get("full_name") or "").strip()
    if not repo_full_name:
        raise HTTPException(status_code=400, detail="Webhook payload missing repository.full_name")

    matching_sources = (
        db.query(ConnectedSource)
        .filter(
            ConnectedSource.source_type == SourceType.GITHUB_REPO,
            ConnectedSource.external_id == repo_full_name,
        )
        .all()
    )
    if not matching_sources:
        return {"status": "ignored", "reason": "No matching connected source", "repository": repo_full_name}

    delivery_id = (x_github_delivery or secrets.token_hex(8)).strip()
    enqueued_jobs: list[str] = []
    deduped = 0

    for src in matching_sources:
        idem_key = f"gh-webhook-{src.id}-{delivery_id}"
        existing_job = db.query(Job).filter(Job.idempotency_key == idem_key).first()
        if existing_job:
            deduped += 1
            continue
        job = enqueue_job(
            db,
            job_type=JobType.SOURCE_IMPORT,
            entity_type="connected_source",
            entity_id=src.id,
            params={"source_id": str(src.id), "webhook_event": event_name, "delivery_id": delivery_id},
            idempotency_key=idem_key,
            queue_name="handoffscope-import",
            task_func="app.workers.import_task.run_import",
        )
        enqueued_jobs.append(str(job.id))

    db.commit()
    return {
        "status": "accepted",
        "event": event_name,
        "delivery_id": delivery_id,
        "jobs_enqueued": enqueued_jobs,
        "deduplicated": deduped,
    }


@router.post("/sources/{source_id}/poll-etag")
def conditional_etag_poll(
    source_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Conditional If-None-Match poll with atomic DB lease window so duplicate workers never race."""
    src = db.query(ConnectedSource).filter(ConnectedSource.id == source_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    require_project_capability(db, user, src.project_id, "source.import")
    if src.source_type != SourceType.GITHUB_REPO:
        raise HTTPException(status_code=400, detail="ETag polling is supported for GitHub repositories")

    cfg = dict(src.config or {})
    owner = (cfg.get("owner") or "").strip()
    repo = (cfg.get("repo") or "").strip()
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="GitHub source missing owner/repo config")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "HandoffScope/1.0",
    }
    tok = decrypt_secret(cfg.get("access_token")) or settings.GITHUB_TOKEN
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    if cfg.get("last_etag"):
        headers["If-None-Match"] = cfg["last_etag"]

    resp = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}/events",
        headers=headers,
        params={"per_page": 10},
        timeout=15,
    )
    if resp.status_code == 304:
        cfg["last_etag_checked_at"] = datetime.now(timezone.utc).isoformat()
        src.config = cfg
        db.commit()
        return {"changed": False, "status_code": 304, "message": "Repository unchanged (304 Not Modified)"}

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"GitHub ETag poll failed ({resp.status_code})")

    new_etag = resp.headers.get("ETag")
    if new_etag:
        cfg["last_etag"] = new_etag
    cfg["last_etag_checked_at"] = datetime.now(timezone.utc).isoformat()
    src.config = cfg

    # Atomic 60-second lease key prevents duplicate background jobs
    lease_bucket = int(datetime.now(timezone.utc).timestamp() // 60)
    job = enqueue_job(
        db,
        job_type=JobType.SOURCE_IMPORT,
        entity_type="connected_source",
        entity_id=src.id,
        created_by_id=user.id,
        params={"source_id": str(src.id), "trigger": "etag_poll"},
        idempotency_key=f"etag-poll-{src.id}-{lease_bucket}",
        queue_name="handoffscope-import",
        task_func="app.workers.import_task.run_import",
    )
    db.commit()
    return {"changed": True, "status_code": 200, "job_id": str(job.id)}
