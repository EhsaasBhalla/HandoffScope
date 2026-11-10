"""Job service — enqueue, track, update background jobs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.enums import JobStatus, JobType
from app.modules.jobs.models import Job

logger = logging.getLogger("handoffscope.jobs")


def get_redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL)


def enqueue_job(
    db: Session,
    *,
    job_type: JobType,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    created_by_id: uuid.UUID | None = None,
    params: dict | None = None,
    idempotency_key: str | None = None,
    queue_name: str = "handoffscope-default",
    task_func: str | None = None,
) -> Job:
    """Create a job record and enqueue it to RQ."""
    # Check idempotency
    if idempotency_key:
        existing = db.query(Job).filter(Job.idempotency_key == idempotency_key).first()
        if existing and existing.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            logger.info("Idempotent job already exists: %s", idempotency_key)
            return existing

    job = Job(
        job_type=job_type,
        status=JobStatus.PENDING,
        entity_type=entity_type,
        entity_id=entity_id,
        created_by_id=created_by_id,
        params=params,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()

    # Enqueue to RQ if a task function path is specified
    if task_func:
        enqueued_to_redis = False
        try:
            redis_conn = get_redis()
            redis_conn.ping()
            q = Queue(queue_name, connection=redis_conn)
            q.enqueue(
                task_func,
                str(job.id),
                job_timeout="30m",
                result_ttl=86400,
            )
            logger.info("Enqueued job %s to queue %s", job.id, queue_name)
            enqueued_to_redis = True
        except Exception as redis_exc:
            logger.info(
                "Redis queue unavailable (%s). Running job %s in local background thread.",
                redis_exc,
                job.id,
            )

        if not enqueued_to_redis:
            # Fallback to local background thread for local development without Redis
            try:
                import importlib
                import threading

                module_name, func_name = task_func.rsplit(".", 1)
                mod = importlib.import_module(module_name)
                func = getattr(mod, func_name)

                thread = threading.Thread(
                    target=func,
                    args=(str(job.id),),
                    daemon=True,
                )
                thread.start()
                logger.info("Executed job %s via fallback local thread", job.id)
            except Exception as thread_exc:
                logger.error("Failed to execute background job %s: %s", job.id, thread_exc)
                job.status = JobStatus.FAILED
                job.error_message = f"Failed to enqueue or execute: {thread_exc}"
                db.flush()

    return job


def update_job_progress(
    db: Session,
    job_id: uuid.UUID,
    *,
    current: int | None = None,
    total: int | None = None,
    message: str | None = None,
) -> Job | None:
    """Update job progress counters."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return None
    if current is not None:
        job.progress_current = current
    if total is not None:
        job.progress_total = total
    if message is not None:
        job.progress_message = message
    db.flush()
    return job


def complete_job(
    db: Session,
    job_id: uuid.UUID,
    *,
    result: dict | None = None,
) -> Job | None:
    """Mark a job as completed."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return None
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(timezone.utc)
    job.result = result
    db.flush()
    return job


def fail_job(
    db: Session,
    job_id: uuid.UUID,
    *,
    error_message: str,
) -> Job | None:
    """Mark a job as failed."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return None

    if job.retry_count < job.max_retries:
        job.status = JobStatus.RETRYING
        job.retry_count += 1
        job.error_message = error_message
    else:
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = error_message

    db.flush()
    return job
