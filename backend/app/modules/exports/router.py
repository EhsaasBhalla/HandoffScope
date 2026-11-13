"""API router for Tamper-Evident Compliance Exports and Cryptographic Bundle Verification."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db
from app.core.exceptions import ForbiddenError
from app.modules.reviews.service import SnapshotIntegrityError
from app.modules.workspaces.models import User

from app.modules.exports.crypto import get_signing_material
from app.modules.exports.schemas import ExportVerificationResultOut, SigningKeyInfoOut
from app.modules.exports.service import (
    ExportStateError,
    generate_certificate_pdf,
    generate_compliance_bundle_zip,
)
from app.modules.exports.verifier import (
    MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES,
    verify_compliance_bundle_bytes,
)

router = APIRouter(tags=["Compliance Exports"])


@router.get("/exports/signing-key", response_model=SigningKeyInfoOut)
def get_export_signing_key(user: User = Depends(get_current_active_user)):
    """Return this instance's public Ed25519 signing key and SHA-256 fingerprint for trusted verification."""
    material = get_signing_material()
    return SigningKeyInfoOut(
        signing_key_id=material.key_id,
        algorithm="Ed25519",
        public_key_fingerprint=material.public_key_fingerprint,
        public_key_pem=material.public_key_pem.decode("utf-8"),
        signer_label="HandoffScope Application Signer",
        persistent_key_configured=material.persistent_configured,
    )


@router.get("/cases/{case_id}/exports/certificate.pdf")
def download_certificate_pdf(
    case_id: uuid.UUID,
    version_id: Optional[uuid.UUID] = Query(default=None),
    version_number: Optional[int] = Query(default=None),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Download a clearance-filtered Executive Handover Certificate PDF for an approved version."""
    try:
        pdf_bytes, filename, _ = generate_certificate_pdf(
            db,
            case_id=case_id,
            user=user,
            version_id=version_id,
            version_number=version_number,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ExportStateError, SnapshotIntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/cases/{case_id}/exports/compliance-bundle.zip")
def download_compliance_bundle_zip(
    case_id: uuid.UUID,
    version_id: Optional[uuid.UUID] = Query(default=None),
    version_number: Optional[int] = Query(default=None),
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Download a SHA-256-manifested and Ed25519-signed offline compliance ZIP bundle."""
    try:
        zip_bytes, filename, _ = generate_compliance_bundle_zip(
            db,
            case_id=case_id,
            user=user,
            version_id=version_id,
            version_number=version_number,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ExportStateError, SnapshotIntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/exports/verify", response_model=ExportVerificationResultOut)
async def verify_compliance_bundle_endpoint(
    file: UploadFile = File(...),
    user: User = Depends(get_current_active_user),
):
    """Verify SHA-256 artifact hashes, Ed25519 signature, and trusted signer identity of an uploaded bundle."""
    raw_bytes = await file.read(MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES + 1)
    if len(raw_bytes) > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Uploaded compliance archive exceeds 25 MB safety limit",
        )
    return verify_compliance_bundle_bytes(raw_bytes)
