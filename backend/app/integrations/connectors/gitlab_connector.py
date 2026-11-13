"""GitLab REST API v4 connector normalizing MRs, Issues, Commits, and Notes."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.db.enums import SourceRecordType
from app.integrations.connectors.base import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
    NormalizedFetchResult,
    parse_iso_dt,
)


class GitLabConnector:
    platform_name = "gitlab"

    def __init__(
        self,
        *,
        project_path: str,
        base_url: str = "https://gitlab.com",
        access_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ):
        self.project_path = project_path.strip().strip("/")
        self.encoded_project = quote_plus(self.project_path)
        self.base_url = (base_url or "https://gitlab.com").rstrip("/")
        self.api_base = f"{self.base_url}/api/v4"
        self.headers = {"Accept": "application/json", "User-Agent": "HandoffScope/1.0"}
        if access_token and access_token.strip():
            self.headers["PRIVATE-TOKEN"] = access_token.strip()
        self._client = httpx.Client(headers=self.headers, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, httpx.Headers]:
        url = f"{self.api_base}{path}"
        for attempt in range(2):
            try:
                resp = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                if attempt == 0:
                    time.sleep(0.3)
                    continue
                raise ConnectorError(f"GitLab HTTP failure on {path}: {type(exc).__name__}", retryable=True) from exc

            if resp.status_code == 401:
                raise ConnectorAuthError("GitLab authentication failed (401 Unauthorized)", status_code=401)
            if resp.status_code == 403:
                raise ConnectorAuthError("GitLab permission denied (403 Forbidden)", status_code=403)
            if resp.status_code == 404:
                raise ConnectorError(f"GitLab project or endpoint not found (404): {self.project_path}", status_code=404)
            if resp.status_code == 429:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise ConnectorRateLimitError("GitLab rate limit exceeded (429)", status_code=429, retryable=True)
            if resp.status_code >= 500:
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                raise ConnectorError(f"GitLab server error ({resp.status_code})", status_code=resp.status_code, retryable=True)

            try:
                return resp.json(), resp.headers
            except ValueError as exc:
                raise ConnectorError(f"Malformed JSON from GitLab on {path}") from exc
        raise ConnectorError("GitLab request retries exhausted", retryable=True)

    def _paginated_get(self, path: str, params: dict[str, Any] | None = None, *, max_pages: int = 3) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page = "1"
        base_params = dict(params or {})
        base_params.setdefault("per_page", 50)

        for _ in range(max_pages):
            req_params = {**base_params, "page": page}
            data, headers = self._request_json(path, params=req_params)
            if not isinstance(data, list) or not data:
                break
            collected.extend(item for item in data if isinstance(item, dict))
            next_page = (headers.get("X-Next-Page") or "").strip()
            if not next_page or next_page == page:
                break
            page = next_page
        return collected

    def validate_credentials(self) -> dict[str, Any]:
        proj, _ = self._request_json(f"/projects/{self.encoded_project}")
        return {
            "project_id": proj.get("id"),
            "path_with_namespace": proj.get("path_with_namespace") or self.project_path,
            "web_url": proj.get("web_url"),
            "default_branch": proj.get("default_branch"),
        }

    def fetch_records(
        self,
        *,
        cursor: str | None = None,
        since: datetime | None = None,
    ) -> NormalizedFetchResult:
        result = NormalizedFetchResult()
        updated_after = cursor or (since.isoformat() if since else None)
        common_params: dict[str, Any] = {"scope": "all", "order_by": "updated_at", "sort": "desc"}
        if updated_after:
            common_params["updated_after"] = updated_after

        max_updated: str | None = cursor

        def _track_ts(raw_ts: str | None) -> None:
            nonlocal max_updated
            if raw_ts and (not max_updated or raw_ts > max_updated):
                max_updated = raw_ts

        # 1. Merge Requests -> mapped into SourceRecordType.PR cleanly with native metadata
        try:
            mrs = self._paginated_get(f"/projects/{self.encoded_project}/merge_requests", params=common_params)
            for idx, mr in enumerate(mrs):
                iid = str(mr.get("iid") or mr.get("id") or "")
                if not iid:
                    continue
                author = mr.get("author") or {}
                raw_state = (mr.get("state") or "opened").lower()
                state_norm = "merged" if raw_state == "merged" else ("closed" if raw_state == "closed" else "open")
                _track_ts(mr.get("updated_at"))
                result.records.append({
                    "source_type": "GITLAB_REPO",
                    "record_type": SourceRecordType.PR,
                    "external_id": f"gl-mr-{iid}",
                    "title": (mr.get("title") or "")[:500],
                    "body": mr.get("description") or "",
                    "author_external_id": author.get("username") or str(author.get("id") or ""),
                    "author_name": author.get("name") or author.get("username"),
                    "state": state_norm,
                    "url": mr.get("web_url"),
                    "external_created_at": parse_iso_dt(mr.get("created_at")),
                    "external_updated_at": parse_iso_dt(mr.get("updated_at")),
                    "metadata_json": {
                        "platform": "gitlab",
                        "native_type": "merge_request",
                        "iid": iid,
                        "labels": mr.get("labels") or [],
                        "target_branch": mr.get("target_branch"),
                        "source_branch": mr.get("source_branch"),
                        "merged_at": mr.get("merged_at"),
                    },
                })
                if idx < 10:
                    try:
                        notes = self._paginated_get(
                            f"/projects/{self.encoded_project}/merge_requests/{iid}/notes",
                            max_pages=1,
                        )
                        ev_list = []
                        for n in notes:
                            if n.get("system"):
                                continue
                            na = n.get("author") or {}
                            ev_list.append({
                                "event_type": "comment",
                                "external_id": f"gl-mr-note-{n.get('id')}",
                                "body": n.get("body") or "",
                                "author_external_id": na.get("username"),
                                "author_name": na.get("name") or na.get("username"),
                                "occurred_at": parse_iso_dt(n.get("created_at")),
                                "metadata_json": {"platform": "gitlab", "mr_iid": iid},
                            })
                        if ev_list:
                            result.events_by_key[(SourceRecordType.PR.value, f"gl-mr-{iid}")] = ev_list
                    except ConnectorError as exc:
                        result.partial_errors.append(f"MR !{iid} notes skipped: {exc}")
        except ConnectorError as exc:
            result.partial_errors.append(f"Merge requests fetch incomplete: {exc}")

        # 2. Issues -> mapped into SourceRecordType.ISSUE
        try:
            issues = self._paginated_get(f"/projects/{self.encoded_project}/issues", params=common_params)
            for issue in issues:
                iid = str(issue.get("iid") or issue.get("id") or "")
                if not iid:
                    continue
                author = issue.get("author") or {}
                raw_state = (issue.get("state") or "opened").lower()
                _track_ts(issue.get("updated_at"))
                result.records.append({
                    "source_type": "GITLAB_REPO",
                    "record_type": SourceRecordType.ISSUE,
                    "external_id": f"gl-issue-{iid}",
                    "title": (issue.get("title") or "")[:500],
                    "body": issue.get("description") or "",
                    "author_external_id": author.get("username") or str(author.get("id") or ""),
                    "author_name": author.get("name") or author.get("username"),
                    "state": "closed" if raw_state == "closed" else "open",
                    "url": issue.get("web_url"),
                    "external_created_at": parse_iso_dt(issue.get("created_at")),
                    "external_updated_at": parse_iso_dt(issue.get("updated_at")),
                    "metadata_json": {
                        "platform": "gitlab",
                        "native_type": "issue",
                        "iid": iid,
                        "labels": issue.get("labels") or [],
                    },
                })
        except ConnectorError as exc:
            result.partial_errors.append(f"Issues fetch incomplete: {exc}")

        # 3. Commits -> mapped into SourceRecordType.COMMIT
        try:
            commit_params: dict[str, Any] = {}
            if updated_after:
                commit_params["since"] = updated_after
            commits = self._paginated_get(f"/projects/{self.encoded_project}/repository/commits", params=commit_params, max_pages=2)
            for c in commits:
                sha = str(c.get("id") or "")
                if not sha:
                    continue
                msg = c.get("message") or c.get("title") or ""
                email = (c.get("author_email") or "").strip() or None
                _track_ts(c.get("committed_date") or c.get("created_at"))
                result.records.append({
                    "source_type": "GITLAB_REPO",
                    "record_type": SourceRecordType.COMMIT,
                    "external_id": sha,
                    "title": (c.get("title") or msg.split("\n")[0])[:500],
                    "body": msg,
                    "author_external_id": c.get("author_name") or email,
                    "author_name": c.get("author_name"),
                    "state": None,
                    "url": c.get("web_url"),
                    "external_created_at": parse_iso_dt(c.get("authored_date") or c.get("created_at")),
                    "external_updated_at": parse_iso_dt(c.get("committed_date") or c.get("created_at")),
                    "metadata_json": {
                        "platform": "gitlab",
                        "native_type": "commit",
                        "short_id": c.get("short_id"),
                        "author_email": email,
                    },
                })
        except ConnectorError as exc:
            result.partial_errors.append(f"Commits fetch incomplete: {exc}")

        result.next_cursor = max_updated
        return result
