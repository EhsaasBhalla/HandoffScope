"""GitHub module — router for OAuth flow, connection status, disconnect."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_db
from app.modules.sources.models import GitHubInstallation
from app.modules.workspaces.models import WorkspaceMembership

logger = logging.getLogger("handoffscope.github")

router = APIRouter(prefix="/github", tags=["GitHub"])


class GitHubStatusResponse(BaseModel):
    connected: bool
    installation_id: int | None = None
    account_login: str | None = None


class GitHubInstallUrlResponse(BaseModel):
    url: str


@router.get("/install-url", response_model=GitHubInstallUrlResponse)
def get_install_url(user=Depends(get_current_active_user)):
    """Return the GitHub App installation URL."""
    if not settings.GITHUB_APP_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App not configured. Use synthetic fixture for demo.",
        )
    url = f"https://github.com/apps/handoffscope/installations/new?state={user.id}"
    return GitHubInstallUrlResponse(url=url)


@router.get("/callback")
async def github_callback(
    code: str = Query(...),
    installation_id: int = Query(...),
    setup_action: str = Query("install"),
    state: str = Query(None),
    db: Session = Depends(get_db),
):
    """Handle GitHub App OAuth callback (async — uses HTTPX)."""
    from app.integrations.github.client import exchange_code_for_token, get_installation_token

    if not settings.GITHUB_APP_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub App not configured")

    # Exchange code for user token (verifies the callback is legitimate)
    token_data = await exchange_code_for_token(code)
    if "error" in token_data:
        raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth error"))

    # Get installation access token
    install_token_data = await get_installation_token(installation_id)

    # Determine workspace from the user state param
    user_id = None
    workspace_id = None
    if state:
        try:
            user_id = uuid.UUID(state)
        except ValueError:
            pass

    if user_id:
        ws_membership = db.query(WorkspaceMembership).filter(
            WorkspaceMembership.user_id == user_id
        ).first()
        if ws_membership:
            workspace_id = ws_membership.workspace_id

    if not workspace_id:
        raise HTTPException(status_code=400, detail="Could not determine workspace")

    # Upsert installation
    existing = db.query(GitHubInstallation).filter(
        GitHubInstallation.installation_id == installation_id
    ).first()

    if existing:
        existing.access_token = install_token_data.get("token")
        existing.token_expires_at = install_token_data.get("expires_at")
    else:
        installation = GitHubInstallation(
            workspace_id=workspace_id,
            installation_id=installation_id,
            account_login=token_data.get("login", "unknown"),
            account_type="Organization",
            access_token=install_token_data.get("token"),
            installed_by_id=user_id,
        )
        db.add(installation)

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


@router.delete("/disconnect")
def disconnect_github(
    workspace_id: uuid.UUID = Query(...),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Remove GitHub App connection from a workspace."""
    installation = db.query(GitHubInstallation).filter(
        GitHubInstallation.workspace_id == workspace_id
    ).first()
    if installation:
        db.delete(installation)
        db.commit()
    return {"message": "GitHub disconnected"}
