"""Project schemas — Pydantic models for projects and memberships."""

from __future__ import annotations

import uuid
from pydantic import BaseModel


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


class AddProjectMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: str = "CONTRIBUTOR"
