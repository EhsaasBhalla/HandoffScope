"""Tests for Phase R3-1: Tamper-Evident Compliance Export PDF/ZIP, Ed25519 signing, clearance redaction, and verifier."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    EvidenceState,
    EvidenceType,
    Priority,
    ReviewState,
    TransitionType,
)
from app.db.session import SessionLocal
from app.main import app
from app.modules.audit.models import AuditEvent
from app.modules.evidence.clearance import RESTRICTED_EVIDENCE_PLACEHOLDER
from app.modules.evidence.models import ClaimEvidence
from app.modules.exports.verifier import verify_compliance_bundle_bytes
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.projects.models import Project
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.service import build_canonical_snapshot_dict
from app.modules.sharing.models import ShareGrant
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


def _login_as(client: TestClient, email: str) -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "handoffscope-dev-2026"},
    )
    assert res.status_code == 200, res.text
    csrf_token = res.cookies.get("csrf_token") or res.json().get("csrf_token", "")
    client.headers.update({"X-CSRF-Token": csrf_token})
    return res.json()["access_token"]


def _seed_export_case_with_restricted_and_versions() -> tuple[uuid.UUID, uuid.UUID, str]:
    from datetime import datetime, timezone

    secret_phrase = f"TOP-SECRET-VAULT-ROOT-{uuid.uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        proj = db.query(Project).first()
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        kabir = db.query(User).filter(User.email == "kabir.singh@example.test").first()
        aisha = db.query(User).filter(User.email == "aisha.khan@example.test").first()

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=901,
            title="R3 Export Compliance Test Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.SHARED,
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()

        db.add(CaseParticipant(case_id=case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT))
        pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Core Credentials & Auth",
            component_area="security",
            sort_order=1,
        )
        db.add(pack)
        db.flush()

        c_public = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.DECISION,
            title="JWT Token Lifetimes",
            body_text="Access token expires in 60 minutes with refresh rotation.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.HIGH,
        )
        c_restricted = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.RISK,
            title="Production Root Key Recovery",
            body_text=f"Vault recovery steps require {secret_phrase} inside HSM.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.CRITICAL,
        )
        db.add_all([c_public, c_restricted])
        db.flush()

        db.add(
            ClaimEvidence(
                id=uuid.uuid4(),
                claim_id=c_restricted.id,
                evidence_type=EvidenceType.DIRECT_REFERENCE,
                excerpt=secret_phrase,
                locator="vault-runbook.md#L1-L10",
                is_restricted=True,
            )
        )
        db.flush()

        now = datetime.now(timezone.utc)
        snap_v1, _, _ = build_canonical_snapshot_dict(
            db,
            case=case,
            version_number=1,
            approved_at=now,
            approved_by_id=kabir.id,
            approved_by_name=kabir.display_name,
        )
        v1 = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=1,
            approved_by_id=kabir.id,
            approved_at=now,
            snapshot_json=snap_v1,
            is_current=False,
        )
        db.add(v1)
        db.flush()

        # Mutate live public claim title & freeze v2 so we prove v1 remains immutable when exported
        c_public.title = "JWT Token Lifetimes V2 UPDATED"
        db.flush()
        snap_v2, _, _ = build_canonical_snapshot_dict(
            db,
            case=case,
            version_number=2,
            approved_at=now,
            approved_by_id=kabir.id,
            approved_by_name=kabir.display_name,
            amendment_reason="Updated token docs in v2",
        )
        v2 = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=2,
            approved_by_id=kabir.id,
            approved_at=now,
            snapshot_json=snap_v2,
            is_current=True,
            amendment_reason="Updated token docs in v2",
            previous_version_id=v1.id,
        )
        db.add(v2)
        db.flush()
        db.add(ShareGrant(handover_version_id=v2.id, recipient_user_id=aisha.id, granted_by=maya.id))

        # Draft case that must NOT be exportable
        draft_case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=902,
            title="R3 Unapproved Draft Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.DRAFT,
            created_by_id=maya.id,
        )
        db.add(draft_case)
        db.commit()
        return case.id, draft_case.id, secret_phrase
    finally:
        db.close()


def test_compliance_export_pdf_zip_verification_and_tamper_detection():
    case_id, draft_case_id, secret_phrase = _seed_export_case_with_restricted_and_versions()
    client = TestClient(app)

    # 1. Draft case must fail cleanly
    _login_as(client, "maya.sharma@example.test")
    assert client.get(f"/api/v1/cases/{draft_case_id}/exports/certificate.pdf").status_code == 400
    assert client.get(f"/api/v1/cases/{draft_case_id}/exports/compliance-bundle.zip").status_code == 400

    # 2. Signing key endpoint returns public info only
    key_res = client.get("/api/v1/exports/signing-key")
    assert key_res.status_code == 200
    key_info = key_res.json()
    assert key_info["algorithm"] == "Ed25519"
    assert "PRIVATE KEY" not in key_info["public_key_pem"]

    # 3. Lead downloads PDF & ZIP for v1 (even though v2 exists)
    pdf_res = client.get(f"/api/v1/cases/{case_id}/exports/certificate.pdf?version_number=1")
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"].startswith("application/pdf")
    assert pdf_res.content.startswith(b"%PDF-")

    zip_res = client.get(f"/api/v1/cases/{case_id}/exports/compliance-bundle.zip?version_number=1")
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"].startswith("application/zip")

    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as zf:
        names = set(zf.namelist())
        assert {
            "certificate.pdf",
            "snapshot.json",
            "acknowledgements.json",
            "responsibility_assignments.json",
            "audit_log.json",
            "manifest.json",
            "certificate.sig",
            "public_key.pem",
            "README_VERIFY.md",
            "verify_bundle.py",
        } <= names
        assert not any("PRIVATE KEY" in zf.read(n).decode("utf-8", errors="ignore") for n in names)

        snap_data = json.loads(zf.read("snapshot.json").decode("utf-8"))
        assert snap_data["export_scope"] == "INTERNAL_FULL"
        assert snap_data["handover_version_number"] == 1
        # Verify v1 preserved original title and wasn't overwritten by v2
        pack_claims = snap_data["snapshot"]["transfer_packs"][0]["claims"]
        assert any(c["title"] == "JWT Token Lifetimes" for c in pack_claims)
        assert not any(c["title"] == "JWT Token Lifetimes V2 UPDATED" for c in pack_claims)
        assert secret_phrase in zf.read("snapshot.json").decode("utf-8")

        verifier_script = zf.read("verify_bundle.py").decode("utf-8")

    # 4. API verify endpoint returns VALID
    verify_res = client.post(
        "/api/v1/exports/verify",
        files={"file": ("bundle.zip", zip_res.content, "application/zip")},
    )
    assert verify_res.status_code == 200, verify_res.text
    v_json = verify_res.json()
    assert v_json["overall_status"] == "VALID"
    assert v_json["integrity_valid"] is True
    assert v_json["signature_valid"] is True
    assert v_json["trusted_signer_verified"] is True

    # 5. Standalone offline verify_bundle.py succeeds with exit code 0
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_zip = Path(tmpdir) / "bundle.zip"
        tmp_script = Path(tmpdir) / "verify_bundle.py"
        tmp_zip.write_bytes(zip_res.content)
        tmp_script.write_text(verifier_script, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(tmp_script), str(tmp_zip), key_info["public_key_fingerprint"]],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "TRUSTED SIGNER VERIFIED" in proc.stdout

    # 6. One-byte mutation in snapshot.json must trigger TAMPERED
    tampered_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as zin, zipfile.ZipFile(tampered_buf, "w") as zout:
        for item in zin.infolist():
            raw = zin.read(item.filename)
            if item.filename == "snapshot.json":
                raw = raw[:-1] + (b"}" if raw[-1:] != b"}" else b" ")
            zout.writestr(item, raw)

    tamper_res = verify_compliance_bundle_bytes(tampered_buf.getvalue())
    assert tamper_res.overall_status == "TAMPERED"
    assert tamper_res.integrity_valid is False
    assert "snapshot.json" in tamper_res.failed_artifacts

    # 7. Untrusted self-signed key distinguishes signature_valid vs trusted_signer_verified
    fake_priv = Ed25519PrivateKey.generate()
    fake_pub_pem = fake_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    import base64, hashlib

    untrusted_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as zin, zipfile.ZipFile(untrusted_buf, "w") as zout:
        manifest_bytes = zin.read("manifest.json")
        fake_sig = {
            "algorithm": "Ed25519",
            "signing_key_id": "rogue-key",
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "signature_b64": base64.b64encode(fake_priv.sign(manifest_bytes)).decode("ascii"),
        }
        for item in zin.infolist():
            if item.filename == "public_key.pem":
                zout.writestr("public_key.pem", fake_pub_pem)
            elif item.filename == "certificate.sig":
                zout.writestr("certificate.sig", json.dumps(fake_sig).encode("utf-8"))
            else:
                zout.writestr(item, zin.read(item.filename))

    untrusted_res = verify_compliance_bundle_bytes(untrusted_buf.getvalue())
    assert untrusted_res.integrity_valid is True
    assert untrusted_res.signature_valid is True
    assert untrusted_res.trusted_signer_verified is False
    assert untrusted_res.overall_status == "VALID_UNTRUSTED_SIGNER"

    # 8. Path traversal entry in ZIP rejected as MALFORMED
    traversal_buf = io.BytesIO()
    with zipfile.ZipFile(traversal_buf, "w") as zbad:
        zbad.writestr("../evil.txt", b"bad")
    assert verify_compliance_bundle_bytes(traversal_buf.getvalue()).overall_status == "MALFORMED"

    # 9. Successor (Aisha) downloads v2 -> RECIPIENT_SAFE: secret_phrase must NEVER appear in PDF/Markdown/JSON
    _login_as(client, "aisha.khan@example.test")
    aisha_zip = client.get(f"/api/v1/cases/{case_id}/exports/compliance-bundle.zip?version_number=2")
    assert aisha_zip.status_code == 200
    with zipfile.ZipFile(io.BytesIO(aisha_zip.content), "r") as zf:
        for member in zf.namelist():
            content = zf.read(member)
            assert secret_phrase.encode("utf-8") not in content, f"Secret leaked in {member}!"
        snap_safe = json.loads(zf.read("snapshot.json").decode("utf-8"))
        assert snap_safe["export_scope"] == "RECIPIENT_SAFE"
        claims_safe = snap_safe["snapshot"]["transfer_packs"][0]["claims"]
        restr_claim = next(c for c in claims_safe if c["title"] == "Production Root Key Recovery")
        assert restr_claim["body_text"] == RESTRICTED_EVIDENCE_PLACEHOLDER

    # Bundle must still verify cleanly for its recipient-safe bytes!
    assert verify_compliance_bundle_bytes(aisha_zip.content).overall_status == "VALID"

    # 10. Audit log contains export events without secret strings
    db = SessionLocal()
    try:
        export_events = (
            db.query(AuditEvent)
            .filter(AuditEvent.entity_id == case_id, AuditEvent.action == "export.compliance_bundle_generated")
            .all()
        )
        assert len(export_events) >= 2
        assert all(secret_phrase not in json.dumps(ev.details or {}) for ev in export_events)
    finally:
        db.close()
