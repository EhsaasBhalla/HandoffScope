"""Workspace service — workspace query, membership management, and tenant isolation."""

from __future__ import annotations

import uuid
import logging
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.db.enums import WorkspaceRole
from app.modules.workspaces.models import User, Workspace, WorkspaceMembership
from app.modules.workspaces.schemas import WorkspaceMemberResponse

logger = logging.getLogger("handoffscope.workspaces")


def get_user_workspaces(db: Session, user_id: uuid.UUID) -> list[Workspace]:
    """Retrieve all workspaces the user is a member of."""
    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.user_id == user_id)
        .all()
    )
    ws_ids = [m.workspace_id for m in memberships]
    if not ws_ids:
        return []
    return db.query(Workspace).filter(Workspace.id.in_(ws_ids)).all()


def get_workspace_membership(
    db: Session,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkspaceMembership | None:
    """Find a specific membership link."""
    return (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        .first()
    )


def add_workspace_member(
    db: Session,
    workspace_id: uuid.UUID,
    email: str,
    role_str: str,
    actor_id: uuid.UUID,
) -> WorkspaceMemberResponse:
    """Add a user to a workspace with role validation and integrity conflict handling."""
    target_user = db.query(User).filter(User.email == email.strip()).first()
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
        ws_role = WorkspaceRole(role_str.upper())
    except ValueError:
        ws_role = WorkspaceRole.MEMBER

    membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=ws_role,
    )
    try:
        db.add(membership)
        db.commit()
        db.refresh(membership)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already in workspace",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return WorkspaceMemberResponse(
        id=membership.id,
        user_id=target_user.id,
        workspace_id=workspace_id,
        role=membership.role.value if hasattr(membership.role, "value") else str(membership.role),
        user_email=target_user.email,
        user_display_name=target_user.display_name,
    )
