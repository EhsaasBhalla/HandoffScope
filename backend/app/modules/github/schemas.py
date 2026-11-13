"""GitHub schemas — Pydantic models for GitHub App integration."""

from __future__ import annotations

from pydantic import BaseModel


class GitHubStatusResponse(BaseModel):
    connected: bool
    installation_id: int | None = None
    account_login: str | None = None


class GitHubInstallUrlResponse(BaseModel):
    url: str
