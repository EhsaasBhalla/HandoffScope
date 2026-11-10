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


class WorkspaceMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str
    user_email: str | None = None
    user_display_name: str | None = None

    model_config = {"from_attributes": True}


class AddWorkspaceMemberRequest(BaseModel):
    email: str
    role: str = "MEMBER"


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_workspace_members(
    workspace_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all members of a workspace."""
    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id)
        .all()
    )
    user_ids = [m.user_id for m in memberships]
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    results = []
    for m in memberships:
        u = users_by_id.get(m.user_id)
        results.append(WorkspaceMemberResponse(
            id=m.id,
            user_id=m.user_id,
            workspace_id=m.workspace_id,
            role=m.role.value if hasattr(m.role, "value") else str(m.role),
            user_email=u.email if u else None,
            user_display_name=u.display_name if u else None,
        ))
    return results


@router.post("/{workspace_id}/members", response_model=WorkspaceMemberResponse, status_code=201)
def add_workspace_member(
    workspace_id: uuid.UUID,
    body: AddWorkspaceMemberRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Add a member to a workspace by email."""
    from app.db.enums import WorkspaceRole

    target_user = db.query(User).filter(User.email == body.email.strip()).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User with this email not found")

    existing = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == target_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="User already in workspace")

    try:
        ws_role = WorkspaceRole(body.role.upper())
    except ValueError:
        ws_role = WorkspaceRole.MEMBER

    membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=ws_role,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)

    return WorkspaceMemberResponse(
        id=membership.id,
        user_id=target_user.id,
        workspace_id=workspace_id,
        role=membership.role.value,
        user_email=target_user.email,
        user_display_name=target_user.display_name,
    )

