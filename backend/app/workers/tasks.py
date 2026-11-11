"""Worker tasks — document parsing, general-purpose background jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import uuid

from app.db.base import SessionLocal
from app.db.enums import (
    ConnectionStatus,
    JobStatus,
    ProcessingStatus,
    SourceRecordType,
    SourceType,
)
from app.modules.documents.models import Document
from app.modules.ingestion.models import SourceRecord
from app.modules.jobs.service import complete_job, fail_job, update_job_progress
from app.modules.sources.models import ConnectedSource
from app.storage.local_storage import LocalStorageBackend

logger = logging.getLogger("handoffscope.worker.tasks")

storage = LocalStorageBackend()


def parse_document_task(job_id: str) -> None:
    """Parse a document file and extract text content.

    Called by RQ worker. The job_id references a Job row whose params
    contains 'document_id'.
    """
    db = SessionLocal()
    try:
        from app.modules.jobs.models import Job

        job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
        if not job:
            logger.error("Job not found: %s", job_id)
            return

        document_id = job.params.get("document_id")
        if not document_id:
            fail_job(db, job.id, error_message="Missing document_id in job params")
            db.commit()
            return

        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not doc:
            fail_job(db, job.id, error_message="Document not found")
            db.commit()
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        update_job_progress(db, job.id, current=0, total=3, message="Loading file")
        db.commit()

        # Load file
        try:
            file_data = storage.load(doc.storage_path)
        except FileNotFoundError:
            doc.processing_status = ProcessingStatus.FAILED
            fail_job(db, job.id, error_message="File not found in storage")
            db.commit()
            return

        update_job_progress(db, job.id, current=1, total=3, message="Parsing content")
        db.commit()

        # Parse based on MIME type or filename extension fallback
        ext = os.path.splitext(doc.original_filename or "")[1].lower()
        mime = (doc.mime_type or "").lower()
        result = None
        try:
            if mime == "application/pdf" or ext == ".pdf":
                from app.integrations.documents.pdf_parser import parse_pdf
                result = parse_pdf(file_data)
            elif (
                mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                or ext == ".docx"
            ):
                from app.integrations.documents.docx_parser import parse_docx
                result = parse_docx(file_data)
            elif mime in ("text/plain", "text/markdown", "text/x-markdown") or ext in (".txt", ".md"):
                from app.integrations.documents.text_parser import parse_text
                result = parse_text(file_data, doc.original_filename)
            else:
                fail_job(db, job.id, error_message=f"Unsupported file type: {doc.mime_type or ext}")
                doc.processing_status = ProcessingStatus.FAILED
                db.commit()
                return
        except Exception as exc:
            logger.error("Parse failed for document %s: %s", document_id, exc)
            db.rollback()
            doc_obj = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
            if doc_obj:
                doc_obj.processing_status = ProcessingStatus.FAILED
            fail_job(db, job.id, error_message=f"Parse error: {exc}")
            db.commit()
            return

        update_job_progress(db, job.id, current=2, total=3, message="Saving results")
        db.commit()

        # Update document with extracted content
        doc.extracted_text = result.get("text", "")
        doc.page_count = result.get("page_count")
        doc.section_count = result.get("section_count") or len(result.get("sections", []))
        doc.extraction_metadata = {
            "quality_warning": result.get("quality_warning"),
            "section_count": len(result.get("sections", [])),
        }
        doc.processing_status = ProcessingStatus.COMPLETED

        # Bridge parsed document into SourceRecord so reconstruction & timeline include uploaded docs
        doc_source = (
            db.query(ConnectedSource)
            .filter(
                ConnectedSource.project_id == doc.project_id,
                ConnectedSource.source_type == SourceType.DOCUMENT_UPLOAD,
            )
            .first()
        )
        if not doc_source:
            doc_source = ConnectedSource(
                project_id=doc.project_id,
                source_type=SourceType.DOCUMENT_UPLOAD,
                name="Uploaded Documents",
                external_id=f"documents-{doc.project_id}",
                connection_status=ConnectionStatus.ACTIVE,
                connected_by_id=doc.uploaded_by_id,
            )
            db.add(doc_source)
            db.flush()

        existing_sr = (
            db.query(SourceRecord)
            .filter(
                SourceRecord.connected_source_id == doc_source.id,
                SourceRecord.record_type == SourceRecordType.DOCUMENT_SECTION,
                SourceRecord.external_id == str(doc.id),
            )
            .first()
        )
        if existing_sr:
            existing_sr.title = doc.original_filename
            existing_sr.body = doc.extracted_text
            existing_sr.sensitivity = doc.sensitivity
            existing_sr.processing_status = ProcessingStatus.COMPLETED
            existing_sr.external_updated_at = datetime.now(timezone.utc)
        else:
            sr = SourceRecord(
                connected_source_id=doc_source.id,
                source_type=SourceType.DOCUMENT_UPLOAD.value,
                record_type=SourceRecordType.DOCUMENT_SECTION,
                external_id=str(doc.id),
                title=doc.original_filename,
                body=doc.extracted_text,
                sensitivity=doc.sensitivity,
                processing_status=ProcessingStatus.COMPLETED,
                external_created_at=doc.created_at,
                external_updated_at=datetime.now(timezone.utc),
                metadata_json={"document_id": str(doc.id), "mime_type": doc.mime_type},
            )
            db.add(sr)

        complete_job(db, job.id, result={
            "page_count": doc.page_count,
            "section_count": doc.section_count,
            "text_length": len(doc.extracted_text),
            "quality_warning": result.get("quality_warning"),
        })
        db.commit()

        logger.info(
            "Document %s parsed: %d chars, %d sections",
            document_id, len(doc.extracted_text), doc.section_count or 0,
        )

    except Exception as exc:
        logger.exception("Unexpected error in parse_document_task: %s", exc)
        try:
            db.rollback()
            fail_job(db, uuid.UUID(job_id), error_message=str(exc))
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
