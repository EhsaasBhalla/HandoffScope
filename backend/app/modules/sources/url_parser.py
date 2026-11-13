"""Shared source URL parsing and repository identity normalization utilities."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def parse_github_repo_identifier(raw: str | None) -> tuple[str, str, str] | None:
    """Parse and normalize a GitHub repository URL or `owner/repo` slug.

    Accepts:
      - https://github.com/owner/repo(.git)
      - http://github.com/owner/repo
      - git@github.com:owner/repo.git
      - owner/repo

    Returns ``(owner, repo, canonical_https_url)`` or ``None`` if input is blank.
    Raises ``ValueError`` if input is non-empty but malformed or points to a non-GitHub host.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    slug = ""
    if text.startswith("git@github.com:"):
        slug = text[len("git@github.com:"):]
    elif "://" in text:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
        if host not in ("github.com", "www.github.com"):
            raise ValueError("Repository URL must point to github.com")
        slug = parsed.path or ""
    elif text.lower().startswith("github.com/"):
        slug = text[len("github.com/"):]
    else:
        slug = text

    slug = slug.strip().strip("/")
    if slug.lower().endswith(".git"):
        slug = slug[:-4]

    parts = [p for p in slug.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repository format. Expected 'owner/repo' or 'https://github.com/owner/repo'.")

    owner, repo = parts[0].strip(), parts[1].strip()
    if not _SEGMENT_RE.match(owner) or not _SEGMENT_RE.match(repo) or owner in (".", "..") or repo in (".", ".."):
        raise ValueError("Repository owner or name contains invalid characters.")

    canonical_url = f"https://github.com/{owner}/{repo}"
    return owner, repo, canonical_url
