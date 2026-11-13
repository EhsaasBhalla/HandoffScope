"""Users API router — profile lookup and workspace user queries."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.modules.auth.router import _build_user_response
from app.modules.auth.schemas import UserResponse
from app.modules.users.schemas import UserProfileResponse
from app.modules.users.service import get_user_by_id
from app.modules.workspaces.models import User, WorkspaceMembership

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return the profile and authoritative RBAC capabilities of the current user."""
    return _build_user_response(db, user)


@router.get("/{user_id}", response_model=UserProfileResponse)
def get_user_profile(
    user_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve public profile for a user who shares at least one workspace."""
    target_user = get_user_by_id(db, user_id)
    if not target_user or not target_user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Verify mutual workspace membership for tenant privacy
    user_ws_ids = {
        m.workspace_id
        for m in db.query(WorkspaceMembership).filter(WorkspaceMembership.user_id == user.id).all()
    }
    target_ws_ids = {
        m.workspace_id
        for m in db.query(WorkspaceMembership).filter(WorkspaceMembership.user_id == target_user.id).all()
    }
    if not (user_ws_ids & target_ws_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access user profile across workspace boundaries",
        )

    return UserProfileResponse.model_validate(target_user)
