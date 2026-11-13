"""Pydantic schemas for Tamper-Evident Compliance Export and Verification."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel


class SigningKeyInfoOut(BaseModel):
    signing_key_id: str
    algorithm: str = "Ed25519"
    public_key_fingerprint: str
    public_key_pem: str
    signer_label: str
    persistent_key_configured: bool


class ExportVerificationResultOut(BaseModel):
    overall_status: str  # VALID | VALID_UNTRUSTED_SIGNER | TAMPERED | INVALID_SIGNATURE | MALFORMED
    integrity_valid: bool
    signature_valid: bool
    trusted_signer_verified: bool
    case_id: Optional[str] = None
    handover_version_id: Optional[str] = None
    handover_version_number: Optional[int] = None
    export_scope: Optional[str] = None
    signing_key_id: Optional[str] = None
    public_key_fingerprint: Optional[str] = None
    artifacts_checked: int = 0
    failed_artifacts: list[str] = []
    missing_artifacts: list[str] = []
    unexpected_entries: list[str] = []
    errors: list[str] = []
