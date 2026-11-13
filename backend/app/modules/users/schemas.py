"""User schemas — Pydantic models for user responses."""

from __future__ import annotations

import uuid
from pydantic import BaseModel

from app.modules.auth.schemas import UserResponse

__all__ = ["UserResponse", "UserProfileResponse"]


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    avatar_url: str | None = None

    model_config = {"from_attributes": True}
