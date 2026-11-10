"""Document service — upload, parse, query documents."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.enums import JobType, ProcessingStatus
from app.modules.documents.models import Document
from app.modules.jobs.service import enqueue_job
from app.storage.local_storage import LocalStorageBackend

logger = logging.getLogger("handoffscope.documents")

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

storage = LocalStorageBackend()


def validate_upload(filename: str, content_type: str, size: int) -> str | None:
    """Validate an upload. Returns error message or None if valid."""
    import os
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        return f"Unsupported MIME type: {content_type}"
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size > max_bytes:
        return f"File too large: {size} bytes. Maximum: {max_bytes} bytes"
    return None


def create_document(
    db: Session,
    *,
    project_id: uuid.UUID,
    filename: str,
    content_type: str,
    file_data: bytes,
    uploaded_by_id: uuid.UUID,
) -> Document:
    """Save uploaded file and create document record."""
    import os

    file_hash = hashlib.sha256(file_data).hexdigest()

    # Check for duplicate
    existing = (
        db.query(Document)
        .filter(Document.project_id == project_id, Document.file_hash == file_hash)
        .first()
    )
    if existing:
        logger.info("Duplicate document detected: %s", filename)
        return existing

    # Generate safe storage name
    ext = os.path.splitext(filename)[1].lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"{project_id}/{safe_name}"

    # Save to storage
    storage.save(storage_path, file_data)

    doc = Document(
        project_id=project_id,
        filename=safe_name,
        original_filename=filename,
        mime_type=content_type,
        file_size=len(file_data),
        storage_path=storage_path,
        file_hash=file_hash,
        processing_status=ProcessingStatus.PENDING,
        uploaded_by_id=uploaded_by_id,
    )
    db.add(doc)
    db.flush()

    # Enqueue parsing job
    enqueue_job(
        db,
        job_type=JobType.DOCUMENT_PARSE,
        entity_type="document",
        entity_id=doc.id,
        created_by_id=uploaded_by_id,
        params={"document_id": str(doc.id)},
        idempotency_key=f"parse-doc-{doc.id}",
        queue_name="handoffscope-import",
        task_func="app.workers.tasks.parse_document_task",
    )

    return doc
