"""Document API router — upload, list, detail."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db, require_project_capability
from app.db.enums import Sensitivity
from app.modules.documents.models import Document
from app.modules.documents.service import create_document, validate_upload
from app.modules.evidence.clearance import has_restricted_clearance
from app.modules.projects.models import Project
from app.storage.factory import load_stored_bytes

router = APIRouter(tags=["Documents"])


class DocumentResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size: int
    processing_status: str
    sensitivity: str
    page_count: int | None = None
    section_count: int | None = None
    created_at: str

    model_config = {"from_attributes": True}


@router.post("/projects/{project_id}/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Upload a document to a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    file_data = await file.read()
    filename = file.filename or "untitled.txt"
    content_type = file.content_type or ""

    error = validate_upload(filename, content_type, len(file_data))
    if error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)

    doc = create_document(
        db,
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        file_data=file_data,
        uploaded_by_id=user.id,
    )
    db.commit()
    db.refresh(doc)

    return DocumentResponse(
        id=doc.id,
        project_id=doc.project_id,
        original_filename=doc.original_filename,
        mime_type=doc.mime_type,
        file_size=doc.file_size,
        processing_status=doc.processing_status.value,
        sensitivity=doc.sensitivity.value,
        page_count=doc.page_count,
        section_count=doc.section_count,
        created_at=doc.created_at.isoformat(),
    )


@router.get("/projects/{project_id}/documents", response_model=list[DocumentResponse])
def list_documents(
    project_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List documents for a project."""
    docs = (
        db.query(Document)
        .filter(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [DocumentResponse(
        id=d.id,
        project_id=d.project_id,
        original_filename=d.original_filename,
        mime_type=d.mime_type,
        file_size=d.file_size,
        processing_status=d.processing_status.value,
        sensitivity=d.sensitivity.value,
        page_count=d.page_count,
        section_count=d.section_count,
        created_at=d.created_at.isoformat(),
    ) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get document detail with processing status."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=doc.id,
        project_id=doc.project_id,
        original_filename=doc.original_filename,
        mime_type=doc.mime_type,
        file_size=doc.file_size,
        processing_status=doc.processing_status.value,
        sensitivity=doc.sensitivity.value,
        page_count=doc.page_count,
        section_count=doc.section_count,
        created_at=doc.created_at.isoformat(),
    )


@router.get("/documents/{document_id}/download")
def download_document_bytes(
    document_id: uuid.UUID,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Stream stored document bytes after enforcing project membership and RESTRICTED clearance."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    require_project_capability(db, user, doc.project_id, "document.view")
    if doc.sensitivity == Sensitivity.RESTRICTED:
        if not has_restricted_clearance(db, user_id=user.id, project_id=doc.project_id, user=user):
            raise HTTPException(status_code=403, detail="Access to restricted document requires elevated clearance")

    try:
        raw = load_stored_bytes(doc.storage_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Stored document object unavailable") from exc

    safe_disp = (doc.original_filename or "document").replace('"', "_")
    return Response(
        content=raw,
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_disp}"',
            "Cache-Control": "no-store",
        },
    )
