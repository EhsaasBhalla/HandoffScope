"""Workspace API router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.workspaces.models import User, Workspace, WorkspaceMembership
from app.modules.workspaces.schemas import (
    AddWorkspaceMemberRequest,
    WorkspaceDetailResponse,
    WorkspaceMemberResponse,
    WorkspaceResponse,
)
from app.modules.workspaces.service import (
    add_workspace_member as service_add_workspace_member,
    get_user_workspaces,
    get_workspace_membership,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])

# Re-export for backward compatibility
__all__ = [
    "WorkspaceResponse",
    "WorkspaceDetailResponse",
    "WorkspaceMemberResponse",
    "AddWorkspaceMemberRequest",
    "router",
]


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """List workspaces the current user belongs to."""
    workspaces = get_user_workspaces(db, user.id)
    return [WorkspaceResponse.model_validate(ws) for ws in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
def get_workspace(workspace_id: uuid.UUID, user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Get workspace detail — only if user is a member."""
    membership = get_workspace_membership(db, workspace_id, user.id)
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


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_workspace_members(
    workspace_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all members of a workspace (workspace membership required)."""
    requester_membership = get_workspace_membership(db, workspace_id, user.id)
    if not requester_membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")

    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id)
        .all()
    )
    user_ids = [m.user_id for m in memberships]
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

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

    requester_membership = get_workspace_membership(db, workspace_id, user.id)
    if not requester_membership or requester_membership.role not in (
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Workspace Owners or Admins can add workspace members",
        )

    return service_add_workspace_member(
        db,
        workspace_id=workspace_id,
        email=body.email,
        role_str=body.role,
        actor_id=user.id,
    )
