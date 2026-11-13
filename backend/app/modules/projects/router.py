"""Project API router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_active_user,
    get_db,
    require_project_capability,
)
from app.db.enums import ConnectionStatus, ProjectRole, SourceType, WorkspaceRole
from app.modules.audit.service import create_audit_event
from app.modules.projects.models import Project, ProjectMembership
from app.modules.sources.models import ConnectedSource
from app.modules.sources.url_parser import parse_github_repo_identifier
from app.modules.workspaces.models import User, WorkspaceMembership

router = APIRouter(tags=["Projects"])


class ProjectResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    repo_url: str | None = None
    connected_source_id: uuid.UUID | None = None
    linked_source_status: str | None = None

    model_config = {"from_attributes": True}


class ProjectCreateRequest(BaseModel):
    name: str
    slug: str
    description: str | None = None
    repo_url: str | None = None
    auto_link_source: bool = True


class ProjectMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    role: str
    user_email: str | None = None
    user_display_name: str | None = None

    model_config = {"from_attributes": True}


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
    return ProjectResponse(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        repo_url=project.repo_url,
        connected_source_id=linked_source.id if linked_source else None,
        linked_source_status=linked_source.connection_status.value if linked_source else None,
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

    # Check slug uniqueness within workspace
    existing = (
        db.query(Project)
        .filter(Project.workspace_id == workspace_id, Project.slug == body.slug)
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project slug already exists in this workspace")

    parsed_repo = None
    normalized_repo_url = body.repo_url.strip() if body.repo_url and body.repo_url.strip() else None
    if normalized_repo_url:
        try:
            parsed_repo = parse_github_repo_identifier(normalized_repo_url)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if parsed_repo:
            normalized_repo_url = parsed_repo[2]

    project = Project(
        workspace_id=workspace_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        repo_url=normalized_repo_url,
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

    linked_source = None
    if parsed_repo and body.auto_link_source:
        owner, repo, canonical_url = parsed_repo
        ext_id = f"{owner}/{repo}"
        linked_source = ConnectedSource(
            project_id=project.id,
            source_type=SourceType.GITHUB_REPO,
            name=ext_id,
            external_id=ext_id,
            connection_status=ConnectionStatus.ACTIVE,
            config={
                "owner": owner,
                "repo": repo,
                "url": canonical_url,
                "auth_mode": "public",
            },
            connected_by_id=user.id,
        )
        db.add(linked_source)
        db.flush()
        create_audit_event(
            db,
            actor_id=user.id,
            action="source.connected",
            entity_type="connected_source",
            entity_id=linked_source.id,
            details={"source_type": SourceType.GITHUB_REPO.value, "external_id": ext_id, "auto_linked": True},
            summary=f"Auto-linked repository source {ext_id} during project creation",
        )

    create_audit_event(
        db,
        actor_id=user.id,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        details={
            "slug": project.slug,
            "repo_url": project.repo_url,
            "connected_source_id": str(linked_source.id) if linked_source else None,
        },
        summary=f"Created project {project.name}",
    )

    db.commit()
    db.refresh(project)
    if linked_source:
        db.refresh(linked_source)

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

    membership = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == body.user_id,
        )
        .first()
    )
    if membership:
        previous_role = membership.role
        if previous_role == ProjectRole.LEAD and proj_role != ProjectRole.LEAD:
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
                    detail="Cannot downgrade the last Project Lead",
                )
        membership.role = proj_role
        create_audit_event(
            db,
            actor_id=user.id,
            action="project.member_role_updated",
            entity_type="project_membership",
            entity_id=membership.id,
            details={
                "project_id": str(project_id),
                "target_user_id": str(target_user.id),
                "previous_role": previous_role.value,
                "new_role": proj_role.value,
            },
            summary=f"Updated {target_user.display_name} project role from {previous_role.value} to {proj_role.value}",
        )
    else:
        membership = ProjectMembership(
            project_id=project_id,
            user_id=body.user_id,
            role=proj_role,
        )
        db.add(membership)
        db.flush()
        create_audit_event(
            db,
            actor_id=user.id,
            action="project.member_added",
            entity_type="project_membership",
            entity_id=membership.id,
            details={
                "project_id": str(project_id),
                "target_user_id": str(target_user.id),
                "role": proj_role.value,
            },
            summary=f"Added {target_user.display_name} to project as {proj_role.value}",
        )

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

    removed_role = membership.role.value
    removed_id = membership.id
    target_user = db.query(User).filter(User.id == user_id).first()
    target_name = target_user.display_name if target_user else str(user_id)

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
    return None

