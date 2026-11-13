"""Project API router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_active_user,
    get_db,
    require_project_capability,
)
from app.db.enums import ProjectRole, SourceType, WorkspaceRole
from app.modules.audit.service import create_audit_event
from app.modules.projects.models import Project, ProjectMembership
from app.modules.projects.schemas import (
    AddProjectMemberRequest,
    ProjectCreateRequest,
    ProjectMemberResponse,
    ProjectResponse,
)
from app.modules.projects.service import (
    add_or_update_project_member as service_add_or_update_project_member,
    create_project as service_create_project,
)
from app.modules.sources.models import ConnectedSource
from app.modules.workspaces.models import User, WorkspaceMembership

router = APIRouter(tags=["Projects"])

# Re-export for backward compatibility
__all__ = [
    "ProjectResponse",
    "ProjectCreateRequest",
    "ProjectMemberResponse",
    "AddProjectMemberRequest",
    "router",
]


def _to_project_response(db: Session, project: Project, linked_source: ConnectedSource | None = None) -> ProjectResponse:
    if linked_source is None and project.repo_url:
        linked_source = (
            db.query(ConnectedSource)
            .filter(
                ConnectedSource.project_id == project.id,
                ConnectedSource.source_type == SourceType.GITHUB_REPO,
            )
            .order_by(ConnectedSource.created_at.asc())
            .first()
        )
    status_val = None
    if linked_source and linked_source.connection_status:
        status_val = (
            linked_source.connection_status.value
            if hasattr(linked_source.connection_status, "value")
            else str(linked_source.connection_status)
        )
    return ProjectResponse(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        repo_url=project.repo_url,
        connected_source_id=linked_source.id if linked_source else None,
        linked_source_status=status_val,
    )


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectResponse])
def list_projects(
    workspace_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List projects in a workspace (user must be a workspace member)."""
    ws_member = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .first()
    )
    if not ws_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")

    projects = db.query(Project).filter(Project.workspace_id == workspace_id).all()
    return [_to_project_response(db, p) for p in projects]


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectResponse, status_code=201)
def create_project(
    workspace_id: uuid.UUID,
    body: ProjectCreateRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new project in a workspace and auto-link a GitHub ConnectedSource if repo_url is given."""
    ws_member = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .first()
    )
    if not ws_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")
    if ws_member.role not in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required capability 'project.create' in workspace",
        )

    project, linked_source = service_create_project(db, workspace_id, body, user)
    return _to_project_response(db, project, linked_source=linked_source)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: uuid.UUID, user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Get project detail."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Check membership: workspace or project level
    ws_member = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == project.workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .first()
    )
    if not ws_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")

    return _to_project_response(db, project)


@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_project_members(
    project_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List members of a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    require_project_capability(db, user, project_id, "project.view")

    memberships = db.query(ProjectMembership).filter(ProjectMembership.project_id == project_id).all()

    user_ids = [m.user_id for m in memberships]
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    results = []
    for m in memberships:
        u = users_by_id.get(m.user_id)
        results.append(ProjectMemberResponse(
            id=m.id,
            user_id=m.user_id,
            project_id=m.project_id,
            role=m.role.value if hasattr(m.role, "value") else str(m.role),
            user_email=u.email if u else None,
            user_display_name=u.display_name if u else None,
        ))
    return results


@router.post("/projects/{project_id}/members", response_model=ProjectMemberResponse, status_code=201)
def add_or_update_project_member(
    project_id: uuid.UUID,
    body: AddProjectMemberRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Add an existing workspace member to a project or update their project role."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    require_project_capability(db, user, project_id, "project.members.manage")

    target_user = db.query(User).filter(User.id == body.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_ws_member = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == project.workspace_id,
            WorkspaceMembership.user_id == target_user.id,
        )
        .first()
    )
    if not target_ws_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target user must belong to the project's workspace before being assigned a project role",
        )

    try:
        proj_role = ProjectRole(body.role.upper())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid project role '{body.role}'. Allowed: LEAD, CONTRIBUTOR, REVIEWER",
        ) from exc

    return service_add_or_update_project_member(
        db,
        project=project,
        target_user=target_user,
        role=proj_role,
        actor_id=user.id,
    )


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Remove a member from a project while protecting the last Project Lead."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    require_project_capability(db, user, project_id, "project.members.manage")

    membership = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project membership not found")

    if membership.role == ProjectRole.LEAD:
        lead_count = (
            db.query(ProjectMembership)
            .filter(
                ProjectMembership.project_id == project_id,
                ProjectMembership.role == ProjectRole.LEAD,
            )
            .count()
        )
        if lead_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove the last Project Lead",
            )

    removed_role = membership.role.value if hasattr(membership.role, "value") else str(membership.role)
    removed_id = membership.id
    target_user = db.query(User).filter(User.id == user_id).first()
    target_name = target_user.display_name if target_user else str(user_id)

    try:
        db.delete(membership)
        create_audit_event(
            db,
            actor_id=user.id,
            action="project.member_removed",
            entity_type="project_membership",
            entity_id=removed_id,
            details={
                "project_id": str(project_id),
                "target_user_id": str(user_id),
                "removed_role": removed_role,
            },
            summary=f"Removed {target_name} ({removed_role}) from project",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return None
