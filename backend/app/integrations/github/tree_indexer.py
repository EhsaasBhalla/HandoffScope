"""Safe, bounded GitHub repository code-tree indexer.

Indexes high-signal architecture, configuration, documentation, and entry-point source
files into normalized SourceRecords while enforcing secret exclusions, binary guards,
per-file/total byte budgets, and incremental blob SHA deduplication.
"""

from __future__ import annotations

import base64
import logging
import posixpath
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.db.enums import ProcessingStatus, Sensitivity, SourceRecordType
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.modules.ingestion.models import SourceRecord
from app.modules.sharing.redactor import redact_secrets_inline

logger = logging.getLogger("handoffscope.github.tree")

_DENIED_PREFIXES = (
    "node_modules/",
    "dist/",
    "build/",
    ".git/",
    ".venv/",
    "venv/",
    "vendor/",
    "__pycache__/",
    ".next/",
    "coverage/",
)
_DENIED_BASENAME_SUBSTRINGS = (
    ".env",
    "secret",
    "credential",
    "id_rsa",
    "id_ed25519",
    ".pfx",
    ".p12",
    ".pem",
    ".key",
    ".keystore",
)
_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf", ".zip", ".gz", ".tar",
    ".7z", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".pyc", ".so", ".dll", ".exe",
    ".bin", ".wasm", ".lock", ".sqlite", ".db",
}
_ALLOWED_TEXT_EXTENSIONS = {
    ".md", ".txt", ".rst", ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".kt", ".rb", ".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".sh", ".sql",
}


def is_eligible_repo_file(entry: dict[str, Any], *, max_single_bytes: int = 32768) -> bool:
    """Strictly allow eligible text blobs and exclude binaries, secrets, symlinks, and submodules."""
    if entry.get("type") != "blob":
        return False
    mode = str(entry.get("mode") or "")
    # Exclude symlinks (120000) and gitlinks/submodules (160000)
    if mode in ("120000", "160000"):
        return False

    raw_path = str(entry.get("path") or "").replace("\\", "/")
    norm = posixpath.normpath(raw_path)
    if not norm or norm.startswith("/") or norm.startswith("../"):
        return False
    low = norm.lower()

    if any(low.startswith(pref) or f"/{pref}" in low for pref in _DENIED_PREFIXES):
        return False

    base = posixpath.basename(low)
    if any(sub in base for sub in _DENIED_BASENAME_SUBSTRINGS):
        return False
    if base.endswith(".min.js") or base.endswith(".min.css") or base in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml"):
        return False

    size = int(entry.get("size") or 0)
    if size <= 0 or size > max_single_bytes:
        return False

    _, ext = posixpath.splitext(base)
    if ext in _BINARY_EXTENSIONS:
        return False
    if ext in _ALLOWED_TEXT_EXTENSIONS or base in ("dockerfile", "makefile", "procfile", "readme", "license"):
        return True
    if base.startswith("dockerfile"):
        return True
    return False


def _priority_rank(path: str) -> tuple[int, str]:
    low = path.lower()
    base = posixpath.basename(low)
    if base.startswith(("readme", "architecture", "contributing", "handoff")):
        return (0, low)
    if base in ("pyproject.toml", "package.json", "cargo.toml", "go.mod") or base.startswith(("dockerfile", "docker-compose")):
        return (1, low)
    if low.startswith((".github/workflows/", "docs/", "adr/")):
        return (2, low)
    if "/main." in f"/{low}" or "/app." in f"/{low}" or "/router" in low or "/auth" in low or "/config" in low:
        return (3, low)
    return (4, low)


def index_github_repo_tree(
    db,
    *,
    client: GitHubClient,
    source_id,
    owner: str,
    repo: str,
    max_total_bytes: int | None = None,
    max_files: int | None = None,
) -> dict[str, Any]:
    """Fetch high-signal repository tree text blobs incrementally into SourceRecords."""
    total_budget = max_total_bytes or settings.GITHUB_TREE_MAX_BYTES
    file_cap = max_files or settings.GITHUB_TREE_MAX_FILES

    repo_meta = client.get_repo(owner, repo)
    default_branch = repo_meta.get("default_branch") or "main"
    branch_meta = client.get_branch(owner, repo, default_branch)
    commit_info = branch_meta.get("commit") or {}
    commit_sha = commit_info.get("sha") or default_branch
    tree_sha = ((commit_info.get("commit") or {}).get("tree") or {}).get("sha") or commit_sha
    commit_dt_raw = (((commit_info.get("commit") or {}).get("committer") or {}).get("date"))
    commit_dt = datetime.fromisoformat(commit_dt_raw.replace("Z", "+00:00")) if commit_dt_raw else datetime.now(timezone.utc)

    tree_resp = client.get_git_tree(owner, repo, tree_sha, recursive=True)
    raw_entries = list(tree_resp.get("tree") or [])
    tree_truncated = bool(tree_resp.get("truncated"))

    # If GitHub truncated recursive tree, fetch top-level subdirectories cleanly with bounded requests
    if tree_truncated:
        top_dirs = [e for e in raw_entries if isinstance(e, dict) and e.get("type") == "tree" and "/" not in str(e.get("path") or "")][:5]
        for td in top_dirs:
            try:
                sub = client.get_git_tree(owner, repo, td["sha"], recursive=False)
                for se in sub.get("tree") or []:
                    if isinstance(se, dict):
                        se_copy = dict(se)
                        se_copy["path"] = f"{td['path']}/{se.get('path', '')}"
                        raw_entries.append(se_copy)
            except GitHubAPIError:
                pass

    eligible = [e for e in raw_entries if isinstance(e, dict) and is_eligible_repo_file(e)]
    eligible.sort(key=lambda e: _priority_rank(str(e["path"])))
    selected = eligible[:file_cap]
    if len(eligible) > file_cap:
        tree_truncated = True

    existing_file_records = {
        rec.external_id: rec
        for rec in db.query(SourceRecord)
        .filter(
            SourceRecord.connected_source_id == source_id,
            SourceRecord.record_type == SourceRecordType.DOCUMENT_SECTION,
            SourceRecord.external_id.like("repo-file:%"),
        )
        .all()
    }

    bytes_used = 0
    created = 0
    updated = 0
    unchanged = 0
    seen_ext_ids: set[str] = set()

    for entry in selected:
        path = str(entry["path"])
        ext_id = f"repo-file:{path}"
        blob_sha = str(entry.get("sha") or "")
        file_size = int(entry.get("size") or 0)

        if bytes_used + file_size > total_budget:
            tree_truncated = True
            break

        seen_ext_ids.add(ext_id)
        existing = existing_file_records.get(ext_id)
        prev_sha = (existing.metadata_json or {}).get("blob_sha") if existing else None
        if existing and prev_sha and prev_sha == blob_sha and existing.state != "deleted":
            unchanged += 1
            bytes_used += file_size
            continue

        try:
            blob = client.get_git_blob(owner, repo, blob_sha)
        except GitHubAPIError as exc:
            logger.warning("Skipping blob %s: %s", path, exc)
            continue

        raw_b64 = blob.get("content") or ""
        encoding = (blob.get("encoding") or "base64").lower()
        try:
            if encoding == "base64":
                decoded_bytes = base64.b64decode(raw_b64.encode("ascii"), validate=False)
                if b"\x00" in decoded_bytes[:512]:
                    continue
                text_content = decoded_bytes.decode("utf-8", errors="replace")
            else:
                text_content = str(raw_b64)
        except Exception:
            continue

        redacted = redact_secrets_inline(text_content)
        clean_body = redacted.redacted_text
        bytes_used += file_size

        meta = {
            "platform": "github",
            "native_type": "repo_file",
            "repo_path": path,
            "blob_sha": blob_sha,
            "commit_sha": commit_sha,
            "default_branch": default_branch,
            "size_bytes": file_size,
            "inline_redactions": redacted.redactions_applied,
        }
        url = f"https://github.com/{owner}/{repo}/blob/{commit_sha}/{path}"

        if existing:
            existing.title = f"Repository File: {path}"
            existing.body = clean_body
            existing.state = "active"
            existing.url = url
            existing.external_updated_at = commit_dt
            existing.metadata_json = meta
            updated += 1
        else:
            rec = SourceRecord(
                connected_source_id=source_id,
                source_type="GITHUB_REPO",
                record_type=SourceRecordType.DOCUMENT_SECTION,
                external_id=ext_id,
                title=f"Repository File: {path}"[:500],
                body=clean_body,
                author_external_id=None,
                author_name=owner,
                state="active",
                url=url,
                sensitivity=Sensitivity.GENERAL,
                processing_status=ProcessingStatus.COMPLETED,
                metadata_json=meta,
                external_created_at=commit_dt,
                external_updated_at=commit_dt,
            )
            db.add(rec)
            created += 1

    # Only mark removed files deleted if the full tree listing wasn't truncated
    deleted_count = 0
    if not tree_truncated:
        for ext_id, rec in existing_file_records.items():
            if ext_id not in seen_ext_ids and rec.state != "deleted":
                rec.state = "deleted"
                rec.external_updated_at = commit_dt
                deleted_count += 1

    db.flush()
    return {
        "files_indexed": created + updated + unchanged,
        "files_created": created,
        "files_updated": updated,
        "files_unchanged": unchanged,
        "files_deleted": deleted_count,
        "bytes_used": bytes_used,
        "tree_truncated": tree_truncated,
        "commit_sha": commit_sha,
    }
