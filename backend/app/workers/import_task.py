"""GitHub import worker task — fetches data from GitHub and creates SourceRecords."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from app.core.config import settings
from app.core.credentials import decrypt_secret
from app.db.base import SessionLocal
from app.db.enums import ConnectionStatus, JobStatus, ProcessingStatus, SourceType, SyncRunStatus
from app.modules.ingestion.models import SourceEvent, SourceRecord
from app.modules.jobs.service import complete_job, fail_job, update_job_progress
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource, GitHubInstallation, SyncRun
from app.integrations.connectors.base import ConnectorError
from app.integrations.connectors.gitlab_connector import GitLabConnector
from app.integrations.connectors.jira_connector import JiraConnector
from app.integrations.connectors.linear_connector import LinearConnector
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.mapper import (
    map_comment,
    map_commit,
    map_issue,
    map_review,
    map_review_comment,
)
from app.integrations.github.tree_indexer import index_github_repo_tree

logger = logging.getLogger("handoffscope.worker.import")


def run_import(job_id: str) -> None:
    """Execute a GitHub source import.

    Fetches issues, PRs, commits, comments, reviews from a GitHub repo
    and creates normalised SourceRecords + SourceEvents.
    """
    db = SessionLocal()
    try:
        from app.modules.jobs.models import Job

        job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
        if not job:
            logger.error("Job not found: %s", job_id)
            return

        source_id = job.params.get("source_id")
        if not source_id:
            fail_job(db, job.id, error_message="Missing source_id")
            db.commit()
            return

        source = db.query(ConnectedSource).filter(
            ConnectedSource.id == uuid.UUID(source_id)
        ).first()
        if not source:
            fail_job(db, job.id, error_message="Source not found")
            db.commit()
            return

        # Create sync run
        sync_run = SyncRun(
            source_id=source.id,
            status=SyncRunStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        db.add(sync_run)

        # Mark job as running
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Handle synthetic fixture sources (no external API calls needed)
        if source.source_type == SourceType.SYNTHETIC_FIXTURE:
            count = (
                db.query(SourceRecord)
                .filter(SourceRecord.connected_source_id == source.id)
                .count()
            )
            sync_run.status = SyncRunStatus.COMPLETED
            sync_run.completed_at = datetime.now(timezone.utc)
            sync_run.records_fetched = count
            sync_run.records_created = 0
            sync_run.records_updated = count
            source.connection_status = ConnectionStatus.ACTIVE
            source.updated_at = datetime.now(timezone.utc)
            complete_job(db, job.id, result={
                "records_fetched": count,
                "records_created": 0,
                "records_updated": count,
                "message": f"Verified {count} synthetic records",
            })
            db.commit()
            logger.info("Synthetic fixture source %s refreshed: %d records", source.id, count)
            return

        # Handle multi-platform connectors (GitLab, Jira, Linear) through shared pipeline
        if source.source_type in (SourceType.GITLAB_REPO, SourceType.JIRA_PROJECT, SourceType.LINEAR_TEAM):
            _run_connector_import(db=db, job=job, source=source, sync_run=sync_run)
            return

        # Get GitHub repo info from source config, falling back to external_id/name (e.g. 'owner/repo')
        config = source.config or {}
        owner = (config.get("owner") or "").strip()
        repo = (config.get("repo") or "").strip()
        if not owner or not repo:
            slug = (source.external_id or source.name or "").strip().strip("/")
            if slug.startswith("https://github.com/"):
                slug = slug.replace("https://github.com/", "").rstrip(".git").strip("/")
            if "/" in slug:
                parts = slug.split("/")
                owner = parts[0].strip()
                repo = parts[1].strip()

        access_token = (
            decrypt_secret(config.get("access_token"))
            or settings.GITHUB_TOKEN
            or os.environ.get("GITHUB_TOKEN", "")
        )
        if not access_token:
            proj = db.query(Project).filter(Project.id == source.project_id).first()
            if proj:
                inst = (
                    db.query(GitHubInstallation)
                    .filter(GitHubInstallation.workspace_id == proj.workspace_id)
                    .first()
                )
                if inst and inst.access_token:
                    access_token = decrypt_secret(inst.access_token)

        if not owner or not repo:
            fail_job(db, job.id, error_message="Source config missing owner/repo")
            sync_run.status = SyncRunStatus.FAILED
            sync_run.completed_at = datetime.now(timezone.utc)
            sync_run.error_message = "Missing owner/repo in config"
            source.connection_status = ConnectionStatus.ERROR
            db.commit()
            return

        client = GitHubClient(access_token)
        records_created = 0
        records_updated = 0
        records_fetched = 0
        records_unchanged = 0
        filtered_pr_issues = 0

        try:
            # ── Fetch Issues (excluding PRs so PRs get canonical data via /pulls) ──
            update_job_progress(db, job.id, current=1, total=4, message=f"Fetching issues from {owner}/{repo}…")
            db.commit()

            issues = client.list_issues(owner, repo)
            pure_issues = [i for i in issues if "pull_request" not in i]
            filtered_pr_issues = max(0, len(issues) - len(pure_issues))
            records_fetched += len(pure_issues)

            for idx, issue_data in enumerate(pure_issues):
                mapped = map_issue(issue_data, force_pr=False)
                record, change = _upsert_record(db, source.id, mapped)
                if change == "created":
                    records_created += 1
                elif change == "updated":
                    records_updated += 1
                else:
                    records_unchanged += 1

                if record and idx < 5:
                    try:
                        comments = client.list_issue_comments(owner, repo, issue_data["number"])
                        records_fetched += len(comments)
                        for comment_data in comments:
                            event_mapped = map_comment(comment_data, str(issue_data["number"]))
                            _upsert_event(db, record.id, event_mapped)
                    except GitHubAPIError as c_err:
                        logger.warning("Skipping comments for issue #%s: %s", issue_data.get("number"), c_err)

            # ── Fetch PRs (reviews + review comments) ─────────
            update_job_progress(db, job.id, current=2, total=4, message=f"Fetching pull requests from {owner}/{repo}…")
            db.commit()

            pulls = client.list_pulls(owner, repo)
            records_fetched += len(pulls)

            for idx, pr_data in enumerate(pulls):
                pr_record, change = _upsert_record(db, source.id, map_issue(pr_data, force_pr=True))
                if change == "created":
                    records_created += 1
                elif change == "updated":
                    records_updated += 1
                else:
                    records_unchanged += 1

                if pr_record and idx < 5:
                    try:
                        reviews = client.list_pull_reviews(owner, repo, pr_data["number"])
                        records_fetched += len(reviews)
                        for review_data in reviews:
                            event_mapped = map_review(review_data, pr_data["number"])
                            _upsert_event(db, pr_record.id, event_mapped)

                        review_comments = client.list_pull_review_comments(owner, repo, pr_data["number"])
                        records_fetched += len(review_comments)
                        for rc_data in review_comments:
                            event_mapped = map_review_comment(rc_data, pr_data["number"])
                            _upsert_event(db, pr_record.id, event_mapped)
                    except GitHubAPIError as pr_err:
                        logger.warning("Skipping reviews/comments for PR #%s: %s", pr_data.get("number"), pr_err)

            # ── Fetch Commits ─────────────────────────────────
            update_job_progress(db, job.id, current=3, total=4, message=f"Fetching commits from {owner}/{repo}…")
            db.commit()

            commits = client.list_commits(owner, repo)
            records_fetched += len(commits)

            for commit_data in commits:
                mapped = map_commit(commit_data)
                record, change = _upsert_record(db, source.id, mapped)
                if change == "created":
                    records_created += 1
                elif change == "updated":
                    records_updated += 1
                else:
                    records_unchanged += 1

            # ── Index High-Signal Repository Tree Files ──
            update_job_progress(db, job.id, current=4, total=4, message=f"Indexing repository files from {owner}/{repo}…")
            db.commit()
            tree_stats: dict = {}
            try:
                tree_stats = index_github_repo_tree(
                    db,
                    client=client,
                    source_id=source.id,
                    owner=owner,
                    repo=repo,
                )
                records_fetched += tree_stats.get("files_indexed", 0)
                records_created += tree_stats.get("files_created", 0)
                records_updated += tree_stats.get("files_updated", 0)
                records_unchanged += tree_stats.get("files_unchanged", 0)
            except GitHubAPIError as tree_err:
                logger.warning("Repo tree indexing skipped/partial for %s/%s: %s", owner, repo, tree_err)
                tree_stats = {"tree_error": str(tree_err)}

            # ── Complete ──────────────────────────────────────
            records_skipped = records_unchanged + filtered_pr_issues
            sync_run.status = SyncRunStatus.COMPLETED
            sync_run.completed_at = datetime.now(timezone.utc)
            sync_run.records_fetched = records_fetched
            sync_run.records_created = records_created
            sync_run.records_updated = records_updated
            source.connection_status = ConnectionStatus.ACTIVE
            source.updated_at = datetime.now(timezone.utc)

            complete_job(db, job.id, result={
                "sync_run_id": str(sync_run.id),
                "records_fetched": records_fetched,
                "records_created": records_created,
                "records_updated": records_updated,
                "records_skipped": records_skipped,
                "filtered_pr_issues": filtered_pr_issues,
                "tree_index": tree_stats,
            })
            db.commit()

            logger.info(
                "Import complete for source %s: fetched=%d created=%d updated=%d",
                source_id, records_fetched, records_created, records_updated,
            )

        except Exception as exc:
            logger.exception("Import failed for source %s: %s", source_id, exc)
            db.rollback()
            # Re-fetch after rollback so state updates succeed cleanly
            sync_run_obj = db.query(SyncRun).filter(SyncRun.id == sync_run.id).first()
            if sync_run_obj:
                sync_run_obj.status = SyncRunStatus.FAILED
                sync_run_obj.error_message = str(exc)[:1000]
                sync_run_obj.completed_at = datetime.now(timezone.utc)
            src_obj = db.query(ConnectedSource).filter(ConnectedSource.id == source.id).first()
            if src_obj:
                src_obj.connection_status = ConnectionStatus.ERROR
            fail_job(db, job.id, error_message=str(exc)[:1000])
            db.commit()

    except Exception as exc:
        logger.exception("Unexpected error in run_import: %s", exc)
        try:
            db.rollback()
            try:
                job_uuid = uuid.UUID(job_id)
                fail_job(db, job_uuid, error_message=str(exc)[:1000])
            except Exception:
                pass
            if 'sync_run' in locals() and sync_run:
                try:
                    s_run = db.query(SyncRun).filter(SyncRun.id == sync_run.id).first()
                    if s_run and s_run.status == SyncRunStatus.RUNNING:
                        s_run.status = SyncRunStatus.FAILED
                        s_run.completed_at = datetime.now(timezone.utc)
                        s_run.error_message = str(exc)[:1000]
                except Exception:
                    pass
            if 'source' in locals() and source:
                try:
                    s_src = db.query(ConnectedSource).filter(ConnectedSource.id == source.id).first()
                    if s_src:
                        s_src.connection_status = ConnectionStatus.ERROR
                except Exception:
                    pass
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _upsert_record(db, source_id: uuid.UUID, data: dict) -> tuple[SourceRecord | None, str]:
    """Insert or update a source record (idempotent by external_id)."""
    existing = (
        db.query(SourceRecord)
        .filter(
            SourceRecord.connected_source_id == source_id,
            SourceRecord.record_type == data["record_type"],
            SourceRecord.external_id == data["external_id"],
        )
        .first()
    )
    if existing:
        changed = False
        for field in ("title", "body", "state", "url", "author_name", "author_external_id"):
            new_val = data.get(field)
            if new_val is not None and getattr(existing, field) != new_val:
                setattr(existing, field, new_val)
                changed = True
        if data.get("external_updated_at") and existing.external_updated_at != data.get("external_updated_at"):
            existing.external_updated_at = data.get("external_updated_at")
            changed = True
        if data.get("metadata_json") and existing.metadata_json != data.get("metadata_json"):
            existing.metadata_json = data.get("metadata_json")
            changed = True
        if changed:
            db.flush()
            return existing, "updated"
        return existing, "unchanged"

    record = SourceRecord(connected_source_id=source_id, **data)
    db.add(record)
    db.flush()
    return record, "created"


def _upsert_event(db, record_id: uuid.UUID, data: dict) -> SourceEvent | None:
    """Insert or skip a source event (idempotent by external_id + event_type)."""
    if not data.get("external_id"):
        # No external_id — insert without dedup
        event = SourceEvent(record_id=record_id, **data)
        db.add(event)
        db.flush()
        return event

    existing = (
        db.query(SourceEvent)
        .filter(
            SourceEvent.record_id == record_id,
            SourceEvent.event_type == data["event_type"],
            SourceEvent.external_id == data["external_id"],
        )
        .first()
    )
    if existing:
        return existing

    event = SourceEvent(record_id=record_id, **data)
    db.add(event)
    db.flush()
    return event


def _build_connector_for_source(source: ConnectedSource):
    cfg = source.config or {}
    if source.source_type == SourceType.GITLAB_REPO:
        return GitLabConnector(
            project_path=cfg.get("project_path") or source.external_id or source.name,
            base_url=cfg.get("base_url") or "https://gitlab.com",
            access_token=decrypt_secret(cfg.get("private_token") or cfg.get("access_token")),
        )
    if source.source_type == SourceType.LINEAR_TEAM:
        return LinearConnector(
            team_key=cfg.get("team_key") or source.external_id or "",
            api_key=decrypt_secret(cfg.get("access_token") or cfg.get("api_token")),
        )
    if source.source_type == SourceType.JIRA_PROJECT:
        return JiraConnector(
            site_url=cfg.get("site_url") or "",
            project_key=cfg.get("project_key") or source.external_id or "",
            email=cfg.get("email") or "",
            api_token=decrypt_secret(cfg.get("api_token")),
        )
    raise ValueError(f"Unsupported connector source type: {source.source_type}")


def _run_connector_import(*, db, job, source: ConnectedSource, sync_run: SyncRun) -> None:
    """Execute normalized incremental import for GitLab, Jira, or Linear sources."""
    cfg = dict(source.config or {})
    cursor = cfg.get("sync_cursor")
    records_created = 0
    records_updated = 0
    records_unchanged = 0
    connector = None

    try:
        connector = _build_connector_for_source(source)
        update_job_progress(
            db,
            job.id,
            current=1,
            total=2,
            message=f"Syncing {connector.platform_name} source {source.name}…",
        )
        db.commit()

        fetched = connector.fetch_records(cursor=cursor)
        update_job_progress(
            db,
            job.id,
            current=2,
            total=2,
            message=f"Normalizing {len(fetched.records)} {connector.platform_name} records…",
        )
        db.commit()

        for rec_dict in fetched.records:
            rec_obj, change = _upsert_record(db, source.id, rec_dict)
            if change == "created":
                records_created += 1
            elif change == "updated":
                records_updated += 1
            else:
                records_unchanged += 1

            if rec_obj:
                key = (
                    rec_dict["record_type"].value
                    if hasattr(rec_dict["record_type"], "value")
                    else str(rec_dict["record_type"]),
                    rec_dict["external_id"],
                )
                for ev in fetched.events_by_key.get(key, []):
                    _upsert_event(db, rec_obj.id, ev)

        if fetched.next_cursor:
            cfg["sync_cursor"] = fetched.next_cursor
            source.config = cfg

        partial = bool(fetched.partial_errors)
        sync_run.status = SyncRunStatus.PARTIAL if partial else SyncRunStatus.COMPLETED
        sync_run.completed_at = datetime.now(timezone.utc)
        sync_run.records_fetched = len(fetched.records)
        sync_run.records_created = records_created
        sync_run.records_updated = records_updated
        if partial:
            sync_run.error_message = "; ".join(fetched.partial_errors)[:1000]
        source.connection_status = ConnectionStatus.ACTIVE
        source.updated_at = datetime.now(timezone.utc)

        complete_job(
            db,
            job.id,
            result={
                "sync_run_id": str(sync_run.id),
                "platform": connector.platform_name,
                "records_fetched": len(fetched.records),
                "records_created": records_created,
                "records_updated": records_updated,
                "records_skipped": records_unchanged,
                "partial_errors": fetched.partial_errors,
            },
        )
        db.commit()
    except (ConnectorError, Exception) as exc:
        logger.warning("Connector import error on source %s: %s", source.id, exc)
        db.rollback()
        sync_obj = db.query(SyncRun).filter(SyncRun.id == sync_run.id).first()
        if sync_obj:
            sync_obj.status = SyncRunStatus.FAILED
            sync_obj.completed_at = datetime.now(timezone.utc)
            sync_obj.error_message = str(exc)[:1000]
        src_obj = db.query(ConnectedSource).filter(ConnectedSource.id == source.id).first()
        if src_obj:
            src_obj.connection_status = ConnectionStatus.ERROR
        fail_job(db, job.id, error_message=str(exc)[:1000])
        db.commit()
    finally:
        if connector and hasattr(connector, "close"):
            try:
                connector.close()
            except Exception:
                pass
