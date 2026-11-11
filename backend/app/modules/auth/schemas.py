"""Auth module — Pydantic schemas for login, tokens, and user responses."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login request body."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """Response after successful login."""

    message: str = "Login successful"
    csrf_token: str
    access_token: str | None = None
    refresh_token: str | None = None
    user: UserResponse


class RefreshRequest(BaseModel):
    """Optional JSON body for POST /api/v1/auth/refresh when 3rd-party cookies are blocked."""

    refresh_token: str | None = None


class UserResponse(BaseModel):
    """Public-facing user data."""

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    avatar_url: str | None = None
    workspace_roles: list[str] = []
    project_roles: dict[str, str] = {}
    capabilities: list[str] = []

    model_config = {"from_attributes": True}


# Resolve forward reference
TokenResponse.model_rebuild()
