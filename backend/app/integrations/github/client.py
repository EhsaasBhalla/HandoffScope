"""GitHub API HTTPX client — async for OAuth callback, sync helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.integrations.github.auth import create_github_app_jwt

logger = logging.getLogger("handoffscope.github.client")

GITHUB_API = "https://api.github.com"
GITHUB_ACCEPT = "application/vnd.github+json"


class GitHubClient:
    """Wrapper around GitHub REST API v3."""

    def __init__(self, access_token: str):
        self.token = access_token
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": GITHUB_ACCEPT,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, url: str, params: dict | None = None) -> dict | list:
        """Synchronous GET request."""
        resp = httpx.get(url, headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _get_paginated(self, url: str, params: dict | None = None, max_pages: int = 20) -> list:
        """Fetch all pages from a paginated GitHub endpoint."""
        params = params or {}
        params.setdefault("per_page", 100)
        all_items = []
        page = 1

        while page <= max_pages:
            params["page"] = page
            resp = httpx.get(url, headers=self._headers, params=params, timeout=30)
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break
            all_items.extend(items)
            if len(items) < params["per_page"]:
                break
            page += 1

        return all_items

    # ── Repo Data Fetchers ────────────────────────────────────

    def get_repo(self, owner: str, repo: str) -> dict:
        return self._get(f"{GITHUB_API}/repos/{owner}/{repo}")

    def list_issues(self, owner: str, repo: str, state: str = "all") -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            params={"state": state, "filter": "all"},
        )

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        )

    def list_pulls(self, owner: str, repo: str, state: str = "all") -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            params={"state": state},
        )

    def list_pull_reviews(self, owner: str, repo: str, pull_number: int) -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/reviews"
        )

    def list_pull_review_comments(self, owner: str, repo: str, pull_number: int) -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/comments"
        )

    def list_commits(self, owner: str, repo: str, since: str | None = None) -> list:
        params = {}
        if since:
            params["since"] = since
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/commits",
            params=params,
        )


async def exchange_code_for_token(code: str) -> dict:
    """Exchange OAuth authorization code for installation access token (async)."""
    from app.core.config import settings

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.GITHUB_APP_CLIENT_ID,
                "client_secret": settings.GITHUB_APP_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


async def get_installation_token(installation_id: int) -> dict:
    """Get an installation access token using the App JWT (async)."""
    app_jwt = create_github_app_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": GITHUB_ACCEPT,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
