"""GitHub import worker task — fetches data from GitHub and creates SourceRecords."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.db.base import SessionLocal
from app.db.enums import ProcessingStatus, SyncRunStatus
from app.modules.ingestion.models import SourceEvent, SourceRecord
from app.modules.jobs.service import complete_job, fail_job, update_job_progress
from app.modules.sources.models import ConnectedSource, SyncRun
from app.integrations.github.client import GitHubClient
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
        job.status = job.status.__class__("RUNNING")
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Get repo info from source config
        config = source.config or {}
        owner = config.get("owner", "")
        repo = config.get("repo", "")
        access_token = config.get("access_token", "")

        if not owner or not repo:
            fail_job(db, job.id, error_message="Source config missing owner/repo")
            sync_run.status = SyncRunStatus.FAILED
            sync_run.error_message = "Missing owner/repo in config"
            db.commit()
            return

        client = GitHubClient(access_token)
        records_created = 0
        records_updated = 0
        records_fetched = 0

        try:
            # ── Fetch Issues ──────────────────────────────────
            update_job_progress(db, job.id, message="Fetching issues…")
            db.commit()

            issues = client.list_issues(owner, repo)
            records_fetched += len(issues)

            for issue_data in issues:
                mapped = map_issue(issue_data)
                record = _upsert_record(db, source.id, mapped)
                if record:
                    records_created += 1

                    # Fetch comments for this issue/PR
                    comments = client.list_issue_comments(owner, repo, issue_data["number"])
                    records_fetched += len(comments)
                    for comment_data in comments:
                        event_mapped = map_comment(comment_data, str(issue_data["number"]))
                        _upsert_event(db, record.id, event_mapped)

            # ── Fetch PRs (reviews + review comments) ─────────
            update_job_progress(db, job.id, message="Fetching pull requests…")
            db.commit()

            pulls = client.list_pulls(owner, repo)
            records_fetched += len(pulls)

            for pr_data in pulls:
                # PR reviews
                reviews = client.list_pull_reviews(owner, repo, pr_data["number"])
                records_fetched += len(reviews)

                pr_record = (
                    db.query(SourceRecord)
                    .filter(
                        SourceRecord.connected_source_id == source.id,
                        SourceRecord.external_id == str(pr_data["number"]),
                    )
                    .first()
                )
                if pr_record:
                    for review_data in reviews:
                        event_mapped = map_review(review_data, pr_data["number"])
                        _upsert_event(db, pr_record.id, event_mapped)

                    # Review comments (inline)
                    review_comments = client.list_pull_review_comments(owner, repo, pr_data["number"])
                    records_fetched += len(review_comments)
                    for rc_data in review_comments:
                        event_mapped = map_review_comment(rc_data, pr_data["number"])
                        _upsert_event(db, pr_record.id, event_mapped)

            # ── Fetch Commits ─────────────────────────────────
            update_job_progress(db, job.id, message="Fetching commits…")
            db.commit()

            commits = client.list_commits(owner, repo)
            records_fetched += len(commits)

            for commit_data in commits:
                mapped = map_commit(commit_data)
                record = _upsert_record(db, source.id, mapped)
                if record:
                    records_created += 1

            # ── Complete ──────────────────────────────────────
            sync_run.status = SyncRunStatus.COMPLETED
            sync_run.completed_at = datetime.now(timezone.utc)
            sync_run.records_fetched = records_fetched
            sync_run.records_created = records_created
            sync_run.records_updated = records_updated

            complete_job(db, job.id, result={
                "records_fetched": records_fetched,
                "records_created": records_created,
                "records_updated": records_updated,
            })
            db.commit()

            logger.info(
                "Import complete for source %s: fetched=%d created=%d",
                source_id, records_fetched, records_created,
            )

        except Exception as exc:
            logger.exception("Import failed for source %s: %s", source_id, exc)
            sync_run.status = SyncRunStatus.FAILED
            sync_run.error_message = str(exc)
            sync_run.completed_at = datetime.now(timezone.utc)
            fail_job(db, job.id, error_message=str(exc))
            db.commit()

    except Exception as exc:
        logger.exception("Unexpected error in run_import: %s", exc)
        try:
            fail_job(db, uuid.UUID(job_id), error_message=str(exc))
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _upsert_record(db, source_id: uuid.UUID, data: dict) -> SourceRecord | None:
    """Insert or skip a source record (idempotent by external_id)."""
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
        return existing

    record = SourceRecord(connected_source_id=source_id, **data)
    db.add(record)
    db.flush()
    return record


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
