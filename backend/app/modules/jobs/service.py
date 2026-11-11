"""Job service — enqueue, track, update background jobs using concurrent background worker pool."""

from __future__ import annotations

import importlib
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.enums import JobStatus, JobType
from app.modules.jobs.models import Job

logger = logging.getLogger("handoffscope.jobs")

# Dedicated background executor pool (zero external Redis dependency)
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="handoffscope-worker")


def _run_task_wrapper(task_func: str, job_id_str: str) -> None:
    """Execute a task function dynamically in a worker thread."""
    try:
        module_name, func_name = task_func.rsplit(".", 1)
        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name)
        func(job_id_str)
    except Exception as exc:
        logger.exception("Error executing background job %s (%s): %s", job_id_str, task_func, exc)


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
    """Create a job record and dispatch it to the background thread pool."""
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

    # Dispatch directly to background thread pool
    if task_func:
        _EXECUTOR.submit(_run_task_wrapper, task_func, str(job.id))
        logger.info("Dispatched background job %s (%s) to worker pool", job.id, task_func)

    return job

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
