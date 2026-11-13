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
from app.storage.factory import get_storage_backend

logger = logging.getLogger("handoffscope.documents")

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/octet-stream",
}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def normalize_mime_type(filename: str | None, content_type: str | None) -> str:
    """Resolve canonical MIME type using file extension when browser omits or sends generic MIME."""
    import os
    ext = os.path.splitext(filename or "")[1].lower()
    raw = (content_type or "").split(";")[0].strip().lower()
    if not raw or raw in ("application/octet-stream", "text/x-markdown"):
        return EXT_TO_MIME.get(ext, raw or "application/octet-stream")
    return raw


def validate_upload(filename: str | None, content_type: str | None, size: int) -> str | None:
    """Validate an upload. Returns error message or None if valid."""
    import os
    if not filename:
        return "Filename is required"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    raw_mime = (content_type or "").split(";")[0].strip().lower()
    if raw_mime and raw_mime not in ALLOWED_MIME_TYPES:
        return f"Unsupported MIME type: {raw_mime}"
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size > max_bytes:
        return f"File too large: {size} bytes. Maximum: {max_bytes} bytes"
    return None


def create_document(
    db: Session,
    *,
    project_id: uuid.UUID,
    filename: str,
    content_type: str | None,
    file_data: bytes,
    uploaded_by_id: uuid.UUID,
) -> Document:
    """Save uploaded file and create document record."""
    import os

    canonical_mime = normalize_mime_type(filename, content_type)
    file_hash = hashlib.sha256(file_data).hexdigest()

    # Check for duplicate
    existing = (
        db.query(Document)
        .filter(Document.project_id == project_id, Document.file_hash == file_hash)
        .first()
    )
    if existing:
        if existing.processing_status == ProcessingStatus.FAILED:
            existing.processing_status = ProcessingStatus.PENDING
            existing.mime_type = canonical_mime
            db.flush()
            enqueue_job(
                db,
                job_type=JobType.DOCUMENT_PARSE,
                entity_type="document",
                entity_id=existing.id,
                created_by_id=uploaded_by_id,
                params={"document_id": str(existing.id)},
                idempotency_key=f"parse-doc-{existing.id}-{uuid.uuid4().hex[:8]}",
                queue_name="handoffscope-import",
                task_func="app.workers.tasks.parse_document_task",
            )
            return existing
        logger.info("Duplicate document detected: %s", filename)
        return existing

    # Generate safe storage name
    ext = os.path.splitext(filename)[1].lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"{project_id}/{safe_name}"

    # Save via configured StorageBackend; roll back stored object if DB flush fails
    backend = get_storage_backend()
    saved_pointer = backend.save(storage_path, file_data)

    doc = Document(
        project_id=project_id,
        filename=safe_name,
        original_filename=filename,
        mime_type=canonical_mime,
        file_size=len(file_data),
        storage_path=saved_pointer,
        file_hash=file_hash,
        processing_status=ProcessingStatus.PENDING,
        uploaded_by_id=uploaded_by_id,
    )
    try:
        db.add(doc)
        db.flush()
    except Exception:
        try:
            backend.delete(saved_pointer)
        except Exception:
            pass
        raise

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
