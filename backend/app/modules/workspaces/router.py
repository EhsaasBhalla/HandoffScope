"""Workspace API router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.workspaces.models import User, Workspace, WorkspaceMembership

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None

    model_config = {"from_attributes": True}


class WorkspaceDetailResponse(WorkspaceResponse):
    member_count: int = 0
    project_count: int = 0


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """List workspaces the current user belongs to."""
    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.user_id == user.id)
        .all()
    )
    ws_ids = [m.workspace_id for m in memberships]
    workspaces = db.query(Workspace).filter(Workspace.id.in_(ws_ids)).all()
    return [WorkspaceResponse.model_validate(ws) for ws in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(workspace_id: uuid.UUID, user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Get workspace detail — only if user is a member."""
    membership = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    member_count = db.query(WorkspaceMembership).filter(WorkspaceMembership.workspace_id == workspace_id).count()
    from app.modules.projects.models import Project
    project_count = db.query(Project).filter(Project.workspace_id == workspace_id).count()

    return WorkspaceDetailResponse(
        id=ws.id,
        name=ws.name,
        slug=ws.slug,
        description=ws.description,
        member_count=member_count,
        project_count=project_count,
    )
