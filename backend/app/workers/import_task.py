"""GitHub import worker task — fetches data from GitHub and creates SourceRecords."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.enums import ConnectionStatus, JobStatus, ProcessingStatus, SourceType, SyncRunStatus
from app.modules.ingestion.models import SourceEvent, SourceRecord
from app.modules.jobs.service import complete_job, fail_job, update_job_progress
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource, GitHubInstallation, SyncRun
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.mapper import (
    map_comment,
    map_commit,
    map_issue,
    map_review,
    map_review_comment,
)

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

        # Get repo info from source config, falling back to external_id/name (e.g. 'owner/repo')
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
            config.get("access_token")
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
                    access_token = inst.access_token

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

        try:
            # ── Fetch Issues (excluding PRs so PRs get canonical data via /pulls) ──
            update_job_progress(db, job.id, current=1, total=4, message=f"Fetching issues from {owner}/{repo}…")
            db.commit()

            issues = client.list_issues(owner, repo)
            pure_issues = [i for i in issues if "pull_request" not in i]
            records_fetched += len(pure_issues)

            for idx, issue_data in enumerate(pure_issues):
                mapped = map_issue(issue_data, force_pr=False)
                record, change = _upsert_record(db, source.id, mapped)
                if change == "created":
                    records_created += 1
                elif change == "updated":
                    records_updated += 1

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

            # ── Complete ──────────────────────────────────────
            sync_run.status = SyncRunStatus.COMPLETED
            sync_run.completed_at = datetime.now(timezone.utc)
            sync_run.records_fetched = records_fetched
            sync_run.records_created = records_created
            sync_run.records_updated = records_updated
            source.connection_status = ConnectionStatus.ACTIVE
            source.updated_at = datetime.now(timezone.utc)

            complete_job(db, job.id, result={
                "records_fetched": records_fetched,
                "records_created": records_created,
                "records_updated": records_updated,
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
            fail_job(db, uuid.UUID(job_id), error_message=str(exc)[:1000])
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
