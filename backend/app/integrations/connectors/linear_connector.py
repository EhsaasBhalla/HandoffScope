"""Linear GraphQL API connector normalizing Issues, Comments, Workflow States, and Assignees."""

from __future__ import annotations

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

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"

_ISSUES_QUERY = """
query HandoffScopeIssues($teamKey: String, $first: Int!, $after: String, $updatedAfter: DateTime) {
  issues(
    first: $first
    after: $after
    filter: {
      team: { key: { eq: $teamKey } }
      updatedAt: { gt: $updatedAfter }
    }
  ) {
    nodes {
      id
      identifier
      title
      description
      url
      priorityLabel
      createdAt
      updatedAt
      state { name type }
      team { id key name }
      project { id name }
      creator { id name displayName email }
      assignee { id name displayName email }
      labels(first: 10) { nodes { name } }
      comments(first: 15) {
        nodes {
          id
          body
          createdAt
          url
          user { id name displayName email }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


class LinearConnector:
    platform_name = "linear"

    def __init__(
        self,
        *,
        team_key: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ):
        token = (api_key or "").strip()
        if not token:
            raise ConnectorAuthError("Linear API key or OAuth token is required", status_code=401)
        # Personal API keys (lin_api_...) pass directly; OAuth tokens use Bearer
        auth_header = token if token.startswith("lin_api_") or token.lower().startswith("bearer ") else f"Bearer {token}"
        self.team_key = team_key.strip().upper()
        self._client = httpx.Client(
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(2):
            try:
                resp = self._client.post(LINEAR_GRAPHQL_URL, json={"query": query, "variables": variables or {}})
            except httpx.HTTPError as exc:
                if attempt == 0:
                    time.sleep(0.3)
                    continue
                raise ConnectorError(f"Linear GraphQL transport failure: {type(exc).__name__}", retryable=True) from exc

            if resp.status_code == 401:
                raise ConnectorAuthError("Linear authentication failed (401)", status_code=401)
            if resp.status_code == 403:
                raise ConnectorAuthError("Linear permission denied (403)", status_code=403)
            if resp.status_code == 429:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise ConnectorRateLimitError("Linear rate limit exceeded", status_code=429, retryable=True)
            if resp.status_code >= 500:
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                raise ConnectorError(f"Linear server error ({resp.status_code})", status_code=resp.status_code, retryable=True)

            try:
                payload = resp.json()
            except ValueError as exc:
                raise ConnectorError("Malformed JSON returned by Linear GraphQL") from exc

            # Linear can return HTTP 200 with a GraphQL errors array
            gql_errors = payload.get("errors")
            if isinstance(gql_errors, list) and gql_errors:
                first_err = gql_errors[0]
                code = str((first_err.get("extensions") or {}).get("code") or "")
                msg = str(first_err.get("message") or "Linear GraphQL error")
                if code == "RATELIMITED":
                    raise ConnectorRateLimitError(msg, status_code=429, retryable=True)
                if code in ("AUTHENTICATION_ERROR", "FORBIDDEN"):
                    raise ConnectorAuthError(msg, status_code=403)
                raise ConnectorError(msg)

            return payload.get("data") or {}
        raise ConnectorError("Linear GraphQL retries exhausted", retryable=True)

    def validate_credentials(self) -> dict[str, Any]:
        data = self._graphql("query Viewer { viewer { id name } }")
        return data.get("viewer") or {}

    def fetch_records(
        self,
        *,
        cursor: str | None = None,
        since: datetime | None = None,
    ) -> NormalizedFetchResult:
        result = NormalizedFetchResult()
        updated_after = cursor or (since.isoformat() if since else None)
        after_cursor: str | None = None
        seen_cursors: set[str] = set()
        max_updated: str | None = cursor

        for _ in range(4):
            variables: dict[str, Any] = {
                "teamKey": self.team_key or None,
                "first": 50,
                "after": after_cursor,
                "updatedAfter": updated_after,
            }
            data = self._graphql(_ISSUES_QUERY, variables=variables)
            conn = data.get("issues") or {}
            nodes = conn.get("nodes") or []
            for issue in nodes:
                if not isinstance(issue, dict):
                    continue
                ident = str(issue.get("identifier") or issue.get("id") or "")
                if not ident:
                    continue
                state_obj = issue.get("state") or {}
                state_type = (state_obj.get("type") or "").lower()
                state_norm = "closed" if state_type in ("completed", "canceled") else "open"
                owner_user = issue.get("assignee") or issue.get("creator") or {}
                labels = [
                    lb.get("name")
                    for lb in ((issue.get("labels") or {}).get("nodes") or [])
                    if isinstance(lb, dict) and lb.get("name")
                ]
                upd = issue.get("updatedAt")
                if upd and (not max_updated or upd > max_updated):
                    max_updated = upd

                result.records.append({
                    "source_type": "LINEAR_TEAM",
                    "record_type": SourceRecordType.ISSUE,
                    "external_id": ident,
                    "title": f"[{ident}] {issue.get('title') or ''}"[:500],
                    "body": issue.get("description") or "",
                    "author_external_id": (owner_user.get("email") or owner_user.get("displayName") or owner_user.get("name") or ""),
                    "author_name": owner_user.get("displayName") or owner_user.get("name"),
                    "state": state_norm,
                    "url": issue.get("url"),
                    "external_created_at": parse_iso_dt(issue.get("createdAt")),
                    "external_updated_at": parse_iso_dt(upd),
                    "metadata_json": {
                        "platform": "linear",
                        "native_type": "sprint_ticket",
                        "identifier": ident,
                        "workflow_state": state_obj.get("name"),
                        "workflow_type": state_obj.get("type"),
                        "priority": issue.get("priorityLabel"),
                        "team_key": (issue.get("team") or {}).get("key"),
                        "project_name": (issue.get("project") or {}).get("name"),
                        "labels": labels,
                        "author_email": owner_user.get("email"),
                    },
                })

                comments = (issue.get("comments") or {}).get("nodes") or []
                ev_list = []
                for cm in comments:
                    if not isinstance(cm, dict) or not cm.get("id"):
                        continue
                    cu = cm.get("user") or {}
                    ev_list.append({
                        "event_type": "comment",
                        "external_id": str(cm["id"]),
                        "body": cm.get("body") or "",
                        "author_external_id": cu.get("displayName") or cu.get("name"),
                        "author_name": cu.get("displayName") or cu.get("name"),
                        "occurred_at": parse_iso_dt(cm.get("createdAt")),
                        "metadata_json": {"platform": "linear", "url": cm.get("url")},
                    })
                if ev_list:
                    result.events_by_key[(SourceRecordType.ISSUE.value, ident)] = ev_list

            page_info = conn.get("pageInfo") or {}
            next_end = page_info.get("endCursor")
            if not page_info.get("hasNextPage") or not next_end or next_end in seen_cursors:
                break
            seen_cursors.add(next_end)
            after_cursor = next_end

        result.next_cursor = max_updated
        return result
