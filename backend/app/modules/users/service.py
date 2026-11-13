"""User service — queries and retrieval helpers."""

from __future__ import annotations

import uuid
import logging
from sqlalchemy.orm import Session

from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.users")


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    """Retrieve user by UUID."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    """Retrieve user by normalized email."""
    return db.query(User).filter(User.email == email.strip().lower()).first()


def list_workspace_users(db: Session, workspace_id: uuid.UUID) -> list[User]:
    """Retrieve all users who belong to the specified workspace."""
    from app.modules.workspaces.models import WorkspaceMembership

    memberships = (
        db.query(WorkspaceMembership)
        .filter(WorkspaceMembership.workspace_id == workspace_id)
        .all()
    )
    user_ids = [m.user_id for m in memberships]
    if not user_ids:
        return []
    return db.query(User).filter(User.id.in_(user_ids), User.is_active.is_(True)).all()
