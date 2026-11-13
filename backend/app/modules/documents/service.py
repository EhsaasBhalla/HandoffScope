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
    if size <= 0:
        return "File cannot be empty"
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


def delete_document(
    db: Session,
    *,
    document: Document,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Safely delete a document, cascading cleanup of chunks, records, and storage file."""
    from app.db.enums import SourceRecordType
    from app.modules.audit.service import create_audit_event
    from app.modules.ingestion.models import SourceRecord
    from app.modules.rag.models import KnowledgeChunk
    from app.storage.factory import get_storage_backend

    doc_id_str = str(document.id)
    storage_path = document.storage_path
    project_id = document.project_id
    filename = document.original_filename

    try:
        # 1. Cascade cleanup KnowledgeChunks associated with this document
        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.source_kind == "DOCUMENT_SECTION",
            KnowledgeChunk.source_ref_id == doc_id_str,
        ).delete(synchronize_session=False)

        # 2. Cascade cleanup SourceRecords (DOCUMENT_SECTION) created for this document
        db.query(SourceRecord).filter(
            SourceRecord.record_type == SourceRecordType.DOCUMENT_SECTION,
            SourceRecord.external_id == doc_id_str,
        ).delete(synchronize_session=False)

        # 3. Delete Document record from database
        db.delete(document)

        # 4. Record audit event
        create_audit_event(
            db,
            actor_id=actor_id,
            action="document.deleted",
            entity_type="document",
            entity_id=uuid.UUID(doc_id_str),
            details={"project_id": str(project_id), "filename": filename},
            summary=f"Deleted document: {filename}",
        )

        db.commit()
    except Exception:
        db.rollback()
        raise

    # 5. Delete from storage backend (graceful error handling so file deletion failure doesn't leave ghost DB record)
    if storage_path:
        try:
            backend = get_storage_backend()
            backend.delete(storage_path)
        except Exception as exc:
            logger.warning("Failed to delete storage file %s for document %s: %s", storage_path, doc_id_str, exc)

