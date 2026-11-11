"""GitHub API HTTPX client — async for OAuth callback, sync helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.integrations.github.auth import create_github_app_jwt

logger = logging.getLogger("handoffscope.github.client")

GITHUB_API = "https://api.github.com"
GITHUB_ACCEPT = "application/vnd.github+json"


class GitHubAPIError(RuntimeError):
    """Raised when GitHub REST API rejects or fails a request."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    """Wrapper around GitHub REST API v3."""

    def __init__(self, access_token: str | None = None):
        self.token = access_token
        self._headers = {
            "Accept": GITHUB_ACCEPT,
            "User-Agent": "HandoffScope/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if access_token and access_token.strip():
            self._headers["Authorization"] = f"Bearer {access_token.strip()}"

    def _raise_for_github_error(self, resp: httpx.Response, url: str) -> None:
        if resp.status_code < 400:
            return
        if resp.status_code in (403, 429):
            rem = resp.headers.get("X-RateLimit-Remaining")
            if rem == "0" or resp.status_code == 429 or "rate limit" in resp.text.lower():
                raise GitHubAPIError(
                    "GitHub API rate limit exceeded. Configure GITHUB_TOKEN or connect a GitHub App installation to increase limits.",
                    status_code=resp.status_code,
                )
            raise GitHubAPIError(f"GitHub API access forbidden (HTTP {resp.status_code}) for {url}", status_code=resp.status_code)
        if resp.status_code == 404:
            raise GitHubAPIError(f"GitHub repository or endpoint not found (404): {url}", status_code=404)
        if resp.status_code == 401:
            raise GitHubAPIError("GitHub authentication failed (401 Unauthorized). Check token.", status_code=401)
        resp.raise_for_status()

    def _get(self, url: str, params: dict | None = None) -> dict | list:
        """Synchronous GET request."""
        try:
            resp = httpx.get(url, headers=self._headers, params=params, timeout=30)
            self._raise_for_github_error(resp, url)
            return resp.json()
        except httpx.HTTPError as exc:
            raise GitHubAPIError(f"GitHub HTTP request failed for {url}: {exc}") from exc

    def _get_paginated(self, url: str, params: dict | None = None, max_pages: int = 2, per_page: int = 50) -> list:
        """Fetch pages from a paginated GitHub endpoint."""
        params = dict(params or {})
        params.setdefault("per_page", per_page)
        all_items = []
        page = 1

        while page <= max_pages:
            params["page"] = page
            try:
                resp = httpx.get(url, headers=self._headers, params=params, timeout=30)
                self._raise_for_github_error(resp, url)
                items = resp.json()
                if not items or not isinstance(items, list):
                    break
                all_items.extend(items)
                if len(items) < params["per_page"]:
                    break
                page += 1
            except GitHubAPIError:
                raise
            except httpx.HTTPError as exc:
                raise GitHubAPIError(f"GitHub request failed for {url} (page {page}): {exc}") from exc

        return all_items

    # ── Repo Data Fetchers ────────────────────────────────────

    def get_repo(self, owner: str, repo: str) -> dict:
        return self._get(f"{GITHUB_API}/repos/{owner}/{repo}")

    def list_issues(self, owner: str, repo: str, state: str = "all") -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            params={"state": state, "filter": "all"},
            max_pages=2,
            per_page=50,
        )

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
            max_pages=1,
            per_page=30,
        )

    def list_pulls(self, owner: str, repo: str, state: str = "all") -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            params={"state": state},
            max_pages=2,
            per_page=50,
        )

    def list_pull_reviews(self, owner: str, repo: str, pull_number: int) -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            max_pages=1,
            per_page=30,
        )

    def list_pull_review_comments(self, owner: str, repo: str, pull_number: int) -> list:
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/comments",
            max_pages=1,
            per_page=30,
        )

    def list_commits(self, owner: str, repo: str, since: str | None = None) -> list:
        params = {}
        if since:
            params["since"] = since
        return self._get_paginated(
            f"{GITHUB_API}/repos/{owner}/{repo}/commits",
            params=params,
            max_pages=2,
            per_page=50,
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
