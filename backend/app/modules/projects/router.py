"""Project API router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.projects.models import Project, ProjectMembership
from app.modules.workspaces.models import WorkspaceMembership

router = APIRouter(tags=["Projects"])


class ProjectResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    repo_url: str | None = None

    model_config = {"from_attributes": True}


class ProjectCreateRequest(BaseModel):
    name: str
    slug: str
    description: str | None = None
    repo_url: str | None = None


class ProjectMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    role: str
    user_email: str | None = None
    user_display_name: str | None = None

    model_config = {"from_attributes": True}


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
    return [ProjectResponse.model_validate(p) for p in projects]


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectResponse, status_code=201)
def create_project(
    workspace_id: uuid.UUID,
    body: ProjectCreateRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new project in a workspace."""
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

    # Check slug uniqueness within workspace
    existing = (
        db.query(Project)
        .filter(Project.workspace_id == workspace_id, Project.slug == body.slug)
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project slug already exists in this workspace")

    from app.db.enums import ProjectRole

    project = Project(
        workspace_id=workspace_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        repo_url=body.repo_url,
    )
    db.add(project)
    db.flush()

    # Auto-add creator as LEAD
    membership = ProjectMembership(
        user_id=user.id,
        project_id=project.id,
        role=ProjectRole.LEAD,
    )
    db.add(membership)
    db.commit()
    db.refresh(project)

    return ProjectResponse.model_validate(project)


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

    return ProjectResponse.model_validate(project)


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

    memberships = db.query(ProjectMembership).filter(ProjectMembership.project_id == project_id).all()
    from app.modules.workspaces.models import User

    results = []
    for m in memberships:
        u = db.query(User).filter(User.id == m.user_id).first()
        results.append(ProjectMemberResponse(
            id=m.id,
            user_id=m.user_id,
            project_id=m.project_id,
            role=m.role.value,
            user_email=u.email if u else None,
            user_display_name=u.display_name if u else None,
        ))
    return results


class AddProjectMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: str = "CONTRIBUTOR"


@router.post("/projects/{project_id}/members", response_model=ProjectMemberResponse, status_code=201)
def add_or_update_project_member(
    project_id: uuid.UUID,
    body: AddProjectMemberRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Add a member to a project or update their role."""
    from app.db.enums import ProjectRole
    from app.modules.workspaces.models import User

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    target_user = db.query(User).filter(User.id == body.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        proj_role = ProjectRole(body.role.upper())
    except ValueError:
        proj_role = ProjectRole.CONTRIBUTOR

    membership = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == body.user_id,
        )
        .first()
    )
    if membership:
        membership.role = proj_role
    else:
        membership = ProjectMembership(
            project_id=project_id,
            user_id=body.user_id,
            role=proj_role,
        )
        db.add(membership)

    db.commit()
    db.refresh(membership)

    return ProjectMemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        project_id=membership.project_id,
        role=membership.role.value,
        user_email=target_user.email,
        user_display_name=target_user.display_name,
    )


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Remove a member from a project."""
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

    db.delete(membership)
    db.commit()
    return None

