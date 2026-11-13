"""Atlassian Jira Cloud REST API v3 connector using `/rest/api/3/search/jql`."""

from __future__ import annotations

import base64
import time
from datetime import datetime
from typing import Any

import httpx

from app.db.enums import SourceRecordType
from app.integrations.connectors.base import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
    NormalizedFetchResult,
    parse_iso_dt,
)


def extract_adf_text(node: Any) -> str:
    """Safely convert Atlassian Document Format (ADF) rich JSON or plain strings into clean text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (extract_adf_text(x) for x in node) if part)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text") or "")
        if node.get("type") == "hardBreak":
            return "\n"
        content = node.get("content")
        if isinstance(content, list):
            joiner = "\n" if node.get("type") in ("doc", "paragraph", "bulletList", "orderedList", "listItem", "heading") else " "
            parts = [extract_adf_text(child) for child in content]
            return joiner.join(p for p in parts if p).strip()
    return ""


class JiraConnector:
    platform_name = "jira"

    def __init__(
        self,
        *,
        site_url: str,
        project_key: str,
        email: str,
        api_token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ):
        clean_site = (site_url or "").strip().rstrip("/")
        if not clean_site.startswith("https://"):
            raise ConnectorError("Jira Cloud site URL must start with https://")
        if not email or not api_token:
            raise ConnectorAuthError("Jira email and API token are required", status_code=401)
        self.site_url = clean_site
        self.project_key = project_key.strip().upper()
        basic = base64.b64encode(f"{email.strip()}:{api_token.strip()}".encode("utf-8")).decode("ascii")
        self._client = httpx.Client(
            headers={"Authorization": f"Basic {basic}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.site_url}{path}"
        for attempt in range(2):
            try:
                resp = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                if attempt == 0:
                    time.sleep(0.3)
                    continue
                raise ConnectorError(f"Jira HTTP failure on {path}: {type(exc).__name__}", retryable=True) from exc

            if resp.status_code == 401:
                raise ConnectorAuthError("Jira authentication failed (401)", status_code=401)
            if resp.status_code == 403:
                raise ConnectorAuthError("Jira access forbidden (403)", status_code=403)
            if resp.status_code == 404:
                raise ConnectorError(f"Jira resource not found (404): {path}", status_code=404)
            if resp.status_code == 410:
                raise ConnectorError(f"Jira endpoint removed (410 Gone): {path}", status_code=410)
            if resp.status_code == 429:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise ConnectorRateLimitError("Jira rate limit exceeded (429)", status_code=429, retryable=True)
            if resp.status_code >= 500:
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                raise ConnectorError(f"Jira server error ({resp.status_code})", status_code=resp.status_code, retryable=True)

            try:
                return resp.json()
            except ValueError as exc:
                raise ConnectorError("Malformed JSON returned by Jira REST API") from exc
        raise ConnectorError("Jira request retries exhausted", retryable=True)

    def validate_credentials(self) -> dict[str, Any]:
        return self._get(f"/rest/api/3/project/{self.project_key}")

    def fetch_records(
        self,
        *,
        cursor: str | None = None,
        since: datetime | None = None,
    ) -> NormalizedFetchResult:
        result = NormalizedFetchResult()
        jql_parts = [f"project = {self.project_key}"]
        since_str = cursor or (since.strftime("%Y-%m-%d %H:%M") if since else None)
        if since_str:
            clean_since = since_str[:16].replace("T", " ")
            jql_parts.append(f'updated >= "{clean_since}"')
        jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"

        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        max_updated: str | None = cursor

        for _ in range(3):
            params: dict[str, Any] = {
                "jql": jql,
                "maxResults": 50,
                "fields": "summary,description,status,issuetype,priority,assignee,reporter,created,updated,labels,comment",
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token

            data = self._get("/rest/api/3/search/jql", params=params)
            issues = data.get("issues") or []
            if not isinstance(issues, list) or not issues:
                break

            for issue in issues:
                key = str(issue.get("key") or issue.get("id") or "")
                if not key:
                    continue
                fields = issue.get("fields") or {}
                status_obj = fields.get("status") or {}
                cat_key = ((status_obj.get("statusCategory") or {}).get("key") or "").lower()
                state_norm = "closed" if cat_key == "done" else "open"

                # Ownership must come from assignee (never force reporter as operational owner)
                assignee = fields.get("assignee") or {}
                reporter = fields.get("reporter") or {}
                author_ext = (
                    assignee.get("accountId")
                    or assignee.get("displayName")
                    or reporter.get("accountId")
                    or reporter.get("displayName")
                )
                author_name = assignee.get("displayName") or reporter.get("displayName")
                upd = fields.get("updated")
                if upd and (not max_updated or upd > max_updated):
                    max_updated = upd

                result.records.append({
                    "source_type": "JIRA_PROJECT",
                    "record_type": SourceRecordType.ISSUE,
                    "external_id": key,
                    "title": f"[{key}] {fields.get('summary') or ''}"[:500],
                    "body": extract_adf_text(fields.get("description")),
                    "author_external_id": author_ext,
                    "author_name": author_name,
                    "state": state_norm,
                    "url": f"{self.site_url}/browse/{key}",
                    "external_created_at": parse_iso_dt(fields.get("created")),
                    "external_updated_at": parse_iso_dt(upd),
                    "metadata_json": {
                        "platform": "jira",
                        "native_type": "sprint_ticket",
                        "issue_key": key,
                        "issue_type": (fields.get("issuetype") or {}).get("name"),
                        "workflow_status": status_obj.get("name"),
                        "priority": (fields.get("priority") or {}).get("name"),
                        "labels": fields.get("labels") or [],
                        "assignee_assigned": bool(assignee),
                        "author_email": assignee.get("emailAddress") or reporter.get("emailAddress"),
                    },
                })

                comments = ((fields.get("comment") or {}).get("comments")) or []
                ev_list = []
                for cm in comments[:15]:
                    if not isinstance(cm, dict) or not cm.get("id"):
                        continue
                    ca = cm.get("author") or {}
                    ev_list.append({
                        "event_type": "comment",
                        "external_id": f"jira-c-{cm['id']}",
                        "body": extract_adf_text(cm.get("body")),
                        "author_external_id": ca.get("accountId") or ca.get("displayName"),
                        "author_name": ca.get("displayName"),
                        "occurred_at": parse_iso_dt(cm.get("created")),
                        "metadata_json": {"platform": "jira", "issue_key": key},
                    })
                if ev_list:
                    result.events_by_key[(SourceRecordType.ISSUE.value, key)] = ev_list

            tok = data.get("nextPageToken")
            if not tok or tok in seen_tokens or data.get("isLast"):
                break
            seen_tokens.add(tok)
            next_page_token = tok

        result.next_cursor = max_updated
        return result
