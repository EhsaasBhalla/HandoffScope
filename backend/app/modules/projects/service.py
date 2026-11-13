"""Project service — project creation, membership management, and RBAC enforcement."""

from __future__ import annotations

import uuid
import logging
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import ConnectionStatus, ProjectRole, SourceType, WorkspaceRole
from app.modules.audit.service import create_audit_event
from app.modules.projects.models import Project, ProjectMembership
from app.modules.projects.schemas import ProjectCreateRequest, ProjectMemberResponse
from app.modules.sources.models import ConnectedSource
from app.modules.sources.url_parser import parse_github_repo_identifier
from app.modules.workspaces.models import User, WorkspaceMembership

logger = logging.getLogger("handoffscope.projects")


def create_project(
    db: Session,
    workspace_id: uuid.UUID,
    body: ProjectCreateRequest,
    user: User,
) -> tuple[Project, ConnectedSource | None]:
    """Create a project within a workspace, auto-linking GitHub source if requested, with transaction safety."""
    # Check slug uniqueness within workspace upfront
    existing = (
        db.query(Project)
        .filter(Project.workspace_id == workspace_id, Project.slug == body.slug)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project with slug '{body.slug}' already exists in this workspace",
        )

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
    linked_source = None

    try:
        db.add(project)
        db.flush()

        # Auto-add creator as LEAD
        membership = ProjectMembership(
            user_id=user.id,
            project_id=project.id,
            role=ProjectRole.LEAD,
        )
        db.add(membership)

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
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project with slug '{body.slug}' already exists in this workspace",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return project, linked_source


def add_or_update_project_member(
    db: Session,
    project: Project,
    target_user: User,
    role: ProjectRole,
    actor_id: uuid.UUID,
) -> ProjectMemberResponse:
    """Add or update a project member safely protecting last Project Lead and catching integrity conflicts."""
    membership = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == target_user.id,
        )
        .first()
    )

    try:
        if membership:
            previous_role = membership.role
            if previous_role == ProjectRole.LEAD and role != ProjectRole.LEAD:
                lead_count = (
                    db.query(ProjectMembership)
                    .filter(
                        ProjectMembership.project_id == project.id,
                        ProjectMembership.role == ProjectRole.LEAD,
                    )
                    .count()
                )
                if lead_count <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Cannot downgrade the last Project Lead",
                    )
            membership.role = role
            create_audit_event(
                db,
                actor_id=actor_id,
                action="project.member_role_updated",
                entity_type="project_membership",
                entity_id=membership.id,
                details={
                    "project_id": str(project.id),
                    "target_user_id": str(target_user.id),
                    "previous_role": previous_role.value if hasattr(previous_role, "value") else str(previous_role),
                    "new_role": role.value if hasattr(role, "value") else str(role),
                },
                summary=f"Updated {target_user.display_name} project role to {role.value}",
            )
        else:
            membership = ProjectMembership(
                project_id=project.id,
                user_id=target_user.id,
                role=role,
            )
            db.add(membership)
            db.flush()
            create_audit_event(
                db,
                actor_id=actor_id,
                action="project.member_added",
                entity_type="project_membership",
                entity_id=membership.id,
                details={
                    "project_id": str(project.id),
                    "target_user_id": str(target_user.id),
                    "role": role.value if hasattr(role, "value") else str(role),
                },
                summary=f"Added {target_user.display_name} to project as {role.value}",
            )

        db.commit()
        db.refresh(membership)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this project",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return ProjectMemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        project_id=membership.project_id,
        role=membership.role.value if hasattr(membership.role, "value") else str(membership.role),
        user_email=target_user.email,
        user_display_name=target_user.display_name,
    )
