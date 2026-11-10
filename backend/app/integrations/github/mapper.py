"""GitHub mapper — converts GitHub API responses to normalised SourceRecords."""

from __future__ import annotations

from datetime import datetime

from app.db.enums import SourceRecordType


def _parse_dt(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def map_issue(issue: dict, source_type: str = "GITHUB_REPO") -> dict:
    """Map a GitHub issue to a SourceRecord dict."""
    is_pr = "pull_request" in issue
    return {
        "source_type": source_type,
        "record_type": SourceRecordType.PR if is_pr else SourceRecordType.ISSUE,
        "external_id": str(issue["number"]),
        "title": issue.get("title", ""),
        "body": issue.get("body") or "",
        "author_external_id": issue.get("user", {}).get("login"),
        "author_name": issue.get("user", {}).get("login"),
        "state": issue.get("state"),
        "url": issue.get("html_url"),
        "external_created_at": _parse_dt(issue.get("created_at")),
        "external_updated_at": _parse_dt(issue.get("updated_at")),
        "metadata_json": {
            "labels": [l.get("name") for l in issue.get("labels", [])],
            "milestone": issue.get("milestone", {}).get("title") if issue.get("milestone") else None,
            "assignees": [a.get("login") for a in issue.get("assignees", [])],
            "is_pull_request": is_pr,
        },
    }


def map_comment(comment: dict, parent_external_id: str) -> dict:
    """Map a GitHub issue/PR comment to a SourceEvent dict."""
    return {
        "event_type": "comment",
        "external_id": str(comment["id"]),
        "body": comment.get("body") or "",
        "author_external_id": comment.get("user", {}).get("login"),
        "author_name": comment.get("user", {}).get("login"),
        "occurred_at": _parse_dt(comment.get("created_at")),
        "metadata_json": {
            "parent_external_id": parent_external_id,
            "url": comment.get("html_url"),
        },
    }


def map_review(review: dict, pr_number: int) -> dict:
    """Map a GitHub PR review to a SourceEvent dict."""
    return {
        "event_type": "review",
        "external_id": str(review["id"]),
        "body": review.get("body") or "",
        "author_external_id": review.get("user", {}).get("login"),
        "author_name": review.get("user", {}).get("login"),
        "occurred_at": _parse_dt(review.get("submitted_at")),
        "metadata_json": {
            "state": review.get("state"),  # APPROVED, CHANGES_REQUESTED, COMMENTED
            "pr_number": pr_number,
            "url": review.get("html_url"),
        },
    }


def map_review_comment(comment: dict, pr_number: int) -> dict:
    """Map a GitHub PR review comment (inline) to a SourceEvent dict."""
    return {
        "event_type": "review_comment",
        "external_id": str(comment["id"]),
        "body": comment.get("body") or "",
        "author_external_id": comment.get("user", {}).get("login"),
        "author_name": comment.get("user", {}).get("login"),
        "occurred_at": _parse_dt(comment.get("created_at")),
        "metadata_json": {
            "pr_number": pr_number,
            "path": comment.get("path"),
            "diff_hunk": comment.get("diff_hunk"),
            "url": comment.get("html_url"),
        },
    }


def map_commit(commit: dict) -> dict:
    """Map a GitHub commit to a SourceRecord dict."""
    author = commit.get("author") or {}
    commit_data = commit.get("commit", {})
    author_info = commit_data.get("author", {})

    return {
        "source_type": "GITHUB_REPO",
        "record_type": SourceRecordType.COMMIT,
        "external_id": commit.get("sha", ""),
        "title": commit_data.get("message", "").split("\n")[0][:500],
        "body": commit_data.get("message", ""),
        "author_external_id": author.get("login"),
        "author_name": author_info.get("name"),
        "state": None,
        "url": commit.get("html_url"),
        "external_created_at": _parse_dt(author_info.get("date")),
        "external_updated_at": _parse_dt(author_info.get("date")),
        "metadata_json": {
            "sha": commit.get("sha"),
            "stats": commit.get("stats"),
            "parents": [p.get("sha") for p in commit.get("parents", [])],
        },
    }
