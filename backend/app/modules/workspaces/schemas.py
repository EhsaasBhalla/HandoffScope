"""Workspace schemas — Pydantic models for workspaces and memberships."""

from __future__ import annotations

import uuid
from pydantic import BaseModel


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None

    model_config = {"from_attributes": True}


class WorkspaceDetailResponse(WorkspaceResponse):
    member_count: int = 0
    project_count: int = 0


class WorkspaceMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str
    user_email: str | None = None
    user_display_name: str | None = None

    model_config = {"from_attributes": True}


class AddWorkspaceMemberRequest(BaseModel):
    email: str
    role: str = "MEMBER"
