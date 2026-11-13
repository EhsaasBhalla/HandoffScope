"""Tests for Phase R3-4: Storage ACLs, GitHub/SSE Hardening, Inline Secret Redaction, and Claim Delegation."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.credentials import decrypt_secret
from app.core.events import _TICKETS
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    EvidenceState,
    EvidenceType,
    Priority,
    ProjectRole,
    ReviewState,
    Sensitivity,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
    TransitionType,
)
from app.db.session import SessionLocal
from app.main import app
from app.modules.documents.models import Document
from app.modules.documents.service import create_document
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.jobs.models import Job
from app.modules.projects.models import Project, ProjectMembership
from app.modules.recipients.models import ResponsibilityAssignment
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.service import build_canonical_snapshot_dict
from app.modules.sharing.models import ShareGrant
from app.modules.sharing.redactor import redact_secrets_inline
from app.modules.sources.models import ConnectedSource, GitHubInstallation
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User, Workspace
from app.storage.s3_storage import S3CompatibleStorageBackend


def _login_as(client: TestClient, email: str) -> None:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "handoffscope-dev-2026"},
    )
    assert res.status_code == 200, res.text
    csrf_token = res.cookies.get("csrf_token") or res.json().get("csrf_token", "")
    client.headers.update({"X-CSRF-Token": csrf_token})


def test_r3_4a_s3_storage_sigv4_rollback_and_document_acl():
    calls: list[tuple[str, str, dict[str, str]]] = []
    store: dict[str, bytes] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), dict(request.headers)))
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ")
        assert "x-amz-content-sha256" in request.headers
        assert "x-amz-date" in request.headers
        key = request.url.path.lstrip("/")
        if request.method == "PUT":
            store[key] = request.content
            return httpx.Response(200, headers={"ETag": '"etag1"'})
        if request.method == "GET":
            if key not in store:
                return httpx.Response(404)
            return httpx.Response(200, content=store[key])
        if request.method == "HEAD":
            return httpx.Response(200 if key in store else 404)
        if request.method == "DELETE":
            store.pop(key, None)
            return httpx.Response(204)
        return httpx.Response(405)

    backend = S3CompatibleStorageBackend(
        endpoint_url="https://account.r2.cloudflarestorage.com",
        bucket="handoff-private",
        access_key_id="AKIA_TEST_KEY",
        secret_access_key="TEST_SECRET_KEY_VALUE",
        region="auto",
        transport=httpx.MockTransport(_handler),
    )

    saved_key = backend.save("proj-1/design.txt", b"architecture bytes")
    assert backend.exists(saved_key) is True
    assert backend.load(saved_key) == b"architecture bytes"
    assert backend.delete(saved_key) is True
    assert backend.exists(saved_key) is False
    assert [m for m, _, _ in calls] == ["PUT", "HEAD", "GET", "DELETE", "HEAD"]

    # DB rollback object cleanup verification
    db = SessionLocal()
    try:
        proj = db.query(Project).first()
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        fake_backend = MagicMock()
        fake_backend.save.return_value = "proj-rollback/temp.txt"

        with patch("app.modules.documents.service.get_storage_backend", return_value=fake_backend):
            with patch.object(db, "flush", side_effect=RuntimeError("simulated db flush failure")):
                try:
                    create_document(
                        db,
                        project_id=proj.id,
                        uploaded_by_id=maya.id,
                        filename="temp.txt",
                        content_type="text/plain",
                        file_data=b"rollback payload",
                    )
                    assert False, "Expected simulated failure"
                except RuntimeError:
                    pass
        fake_backend.delete.assert_called_once_with("proj-rollback/temp.txt")

        # Seed a non-restricted & restricted document for ACL download checks
        with patch("app.modules.documents.service.get_storage_backend", return_value=backend):
            doc_public = create_document(
                db,
                project_id=proj.id,
                uploaded_by_id=maya.id,
                filename="public-arch.md",
                content_type="text/markdown",
                file_data=b"# Public Architecture",
            )
            doc_public.sensitivity = Sensitivity.INTERNAL
            doc_restricted = create_document(
                db,
                project_id=proj.id,
                uploaded_by_id=maya.id,
                filename="secret-keys.txt",
                content_type="text/plain",
                file_data=b"Restricted ops guide",
            )
            doc_restricted.sensitivity = Sensitivity.RESTRICTED
            db.commit()
            pub_id = doc_public.id
            res_id = doc_restricted.id

        # Create outsider user not in project
        outsider_email = f"outsider-{uuid.uuid4().hex[:6]}@example.test"
        outsider = User(
            id=uuid.uuid4(),
            email=outsider_email,
            display_name="Outsider User",
            password_hash=maya.password_hash,
            is_active=True,
        )
        db.add(outsider)
        db.commit()
    finally:
        db.close()

    with patch("app.storage.factory.get_storage_backend", return_value=backend):
        with TestClient(app) as client:
            # Non-member blocked
            _login_as(client, outsider_email)
            r_out = client.get(f"/api/v1/documents/{pub_id}/download")
            assert r_out.status_code == 403

            # Regular contributor without restricted clearance cannot download RESTRICTED document
            _login_as(client, "kabir.singh@example.test")
            r_pub = client.get(f"/api/v1/documents/{pub_id}/download")
            assert r_pub.status_code == 200
            assert b"Public Architecture" in r_pub.content
            r_res_denied = client.get(f"/api/v1/documents/{res_id}/download")
            assert r_res_denied.status_code == 403

            # Lead with restricted clearance can download RESTRICTED document
            _login_as(client, "maya.sharma@example.test")
            r_res_ok = client.get(f"/api/v1/documents/{res_id}/download")
            assert r_res_ok.status_code == 200
            assert b"Restricted ops guide" in r_res_ok.content


def test_r3_4b_github_hardening_and_sse_ticket_guards(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_APP_CLIENT_ID", "gh_client_test")
    monkeypatch.setattr(settings, "GITHUB_APP_CLIENT_SECRET", "gh_secret_test")
    monkeypatch.setattr(settings, "GITHUB_APP_WEBHOOK_SECRET", "whsec_test_123456")

    db = SessionLocal()
    try:
        proj = db.query(Project).first()
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        src = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="org/etag-repo",
            external_id="org/etag-repo",
            config={"owner": "org", "repo": "etag-repo"},
        )
        db.add(src)
        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=944,
            title="SSE Hardening Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.DRAFT,
            created_by_id=maya.id,
        )
        db.add(case)
        outsider_email = f"sse-out-{uuid.uuid4().hex[:6]}@example.test"
        db.add(
            User(
                id=uuid.uuid4(),
                email=outsider_email,
                display_name="SSE Outsider",
                password_hash=maya.password_hash,
                is_active=True,
            )
        )
        db.commit()
        source_id = src.id
        case_id = case.id
    finally:
        db.close()

    with TestClient(app) as client:
        # 1. Signed OAuth state + encrypted GitHubInstallation token
        _login_as(client, "maya.sharma@example.test")
        install_res = client.get("/api/v1/github/install-url")
        assert install_res.status_code == 200
        install_url = install_res.json()["url"]
        state_token = install_url.split("state=")[-1].split("&")[0]

        bad_cb = client.get(
            "/api/v1/github/callback",
            params={"code": "abc", "installation_id": 77711, "state": "tampered.state"},
            follow_redirects=False,
        )
        assert bad_cb.status_code == 400

        with (
            patch(
                "app.integrations.github.client.exchange_code_for_token",
                return_value={"access_token": "gho_user_secret_token"},
            ),
            patch(
                "app.integrations.github.client.get_installation_token",
                return_value={"token": "ghs_install_secret_token", "expires_at": datetime.now(timezone.utc).isoformat()},
            ),
        ):
            ok_cb = client.get(
                "/api/v1/github/callback",
                params={"code": "valid-code", "installation_id": 77711, "state": state_token},
                follow_redirects=False,
            )
            assert ok_cb.status_code in (200, 307)

        db2 = SessionLocal()
        try:
            inst = db2.query(GitHubInstallation).filter(GitHubInstallation.installation_id == 77711).first()
            assert inst is not None
            assert inst.access_token.startswith("enc:v1:")
            assert decrypt_secret(inst.access_token) == "ghs_install_secret_token"
        finally:
            db2.close()

        # 2. Webhook HMAC verification & delivery dedup
        payload = json.dumps({"repository": {"full_name": "org/etag-repo"}}).encode("utf-8")
        bad_sig = client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=deadbeef",
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-001",
            },
        )
        assert bad_sig.status_code == 401

        created_jobs: list[Job] = []

        def _fake_enqueue(db_sess, **kwargs):
            j = Job(
                id=uuid.uuid4(),
                job_type=kwargs["job_type"],
                entity_type=kwargs.get("entity_type"),
                entity_id=kwargs.get("entity_id"),
                idempotency_key=kwargs.get("idempotency_key"),
            )
            db_sess.add(j)
            db_sess.flush()
            created_jobs.append(j)
            return j

        sig = "sha256=" + hmac.new(b"whsec_test_123456", payload, hashlib.sha256).hexdigest()
        with patch("app.modules.github.router.enqueue_job", side_effect=_fake_enqueue):
            ok_wh = client.post(
                "/api/v1/github/webhook",
                content=payload,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "delivery-001",
                },
            )
            assert ok_wh.status_code == 202
            assert ok_wh.json()["status"] == "accepted"
            assert len(ok_wh.json()["jobs_enqueued"]) == 1
            assert ok_wh.json()["deduplicated"] == 0

            dup_wh = client.post(
                "/api/v1/github/webhook",
                content=payload,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "delivery-001",
                },
            )
            assert dup_wh.status_code == 202
            assert dup_wh.json()["jobs_enqueued"] == []
            assert dup_wh.json()["deduplicated"] == 1
            assert len(created_jobs) == 1

        # 3. ETag conditional poll: 200 -> saves ETag & queues once; 304 -> unchanged
        with (
            patch("httpx.get") as mock_get,
            patch("app.modules.github.router.enqueue_job", side_effect=_fake_enqueue),
        ):
            before_poll = len(created_jobs)
            mock_get.return_value = httpx.Response(200, json=[], headers={"ETag": 'W/"abc-etag"'})
            p1 = client.post(f"/api/v1/github/sources/{source_id}/poll-etag")
            assert p1.status_code == 200
            assert p1.json()["changed"] is True
            assert p1.json()["status_code"] == 200
            assert len(created_jobs) == before_poll + 1

            mock_get.return_value = httpx.Response(304)
            p2 = client.post(f"/api/v1/github/sources/{source_id}/poll-etag")
            assert p2.status_code == 200
            assert p2.json()["changed"] is False
            assert p2.json()["status_code"] == 304
            assert len(created_jobs) == before_poll + 1
            assert mock_get.call_args_list[-1].kwargs["headers"].get("If-None-Match") == 'W/"abc-etag"'

        # 4. SSE ticket authorization, cross-case guard, and single-use replay rejection
        _login_as(client, outsider_email)
        t_denied = client.post(f"/api/v1/cases/{case_id}/events/ticket")
        assert t_denied.status_code == 403

        _login_as(client, "maya.sharma@example.test")
        t_ok = client.post(f"/api/v1/cases/{case_id}/events/ticket")
        assert t_ok.status_code == 200
        ticket = t_ok.json()["ticket"]

        # Cross-case ticket consumption via HTTP is denied (401)
        other_case_id = uuid.uuid4()
        cross_res = client.get(f"/api/v1/cases/{other_case_id}/events/stream", params={"ticket": ticket})
        assert cross_res.status_code == 401

        # Fresh ticket: single-use consumption succeeds once and replay over HTTP is rejected (401)
        t_ok2 = client.post(f"/api/v1/cases/{case_id}/events/ticket")
        assert t_ok2.status_code == 200
        ticket2 = t_ok2.json()["ticket"]
        assert _TICKETS.consume(ticket=ticket2, case_id=case_id) is not None
        s_replay = client.get(f"/api/v1/cases/{case_id}/events/stream", params={"ticket": ticket2})
        assert s_replay.status_code == 401


def test_r3_4c_inline_secret_redaction_and_db_preservation():
    raw_pg = "postgresql://prod_admin:Sup3rS3cr3tPass99@pg.internal.net:5432/handoff"
    raw_gh = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    placeholder = "postgresql://user:example@localhost:5432/db and ghp_example_placeholder_token_12345"

    res = redact_secrets_inline(f"Connect via {raw_pg} and token {raw_gh}. Safe id=token_ttl_seconds")
    assert "Sup3rS3cr3tPass99" not in res.redacted_text
    assert raw_gh not in res.redacted_text
    assert "[REDACTED:CONNECTION_URI]" in res.redacted_text
    assert "[REDACTED:SECRET]" in res.redacted_text
    assert "token_ttl_seconds" in res.redacted_text
    assert res.redactions_applied >= 2

    ph_res = redact_secrets_inline(placeholder)
    assert ph_res.redactions_applied == 0
    assert ph_res.redacted_text == placeholder

    # Seed case with secret embedded in claim body; verify recipient view & RECIPIENT_SAFE export redact it
    db = SessionLocal()
    try:
        proj = db.query(Project).first()
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        aisha = db.query(User).filter(User.email == "aisha.khan@example.test").first()

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=945,
            title="Secret Redaction Export Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.SHARED,
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()
        db.add(CaseParticipant(case_id=case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT))
        pack = TransferPack(id=uuid.uuid4(), case_id=case.id, name="Database Runbook", component_area="db")
        db.add(pack)
        db.flush()

        claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.OPERATIONAL_NOTE,
            title="Primary DB Failover Credentials",
            body_text=f"Failover uses {raw_pg} during emergency promotion.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.HIGH,
        )
        db.add(claim)
        db.flush()

        snapshot, _, _ = build_canonical_snapshot_dict(
            db,
            case=case,
            version_number=1,
            approved_at=datetime.now(timezone.utc),
            approved_by_id=maya.id,
            approved_by_name=maya.display_name,
        )
        version = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=1,
            snapshot_json=snapshot,
            approved_by_id=maya.id,
            approved_at=datetime.now(timezone.utc),
            is_current=True,
        )
        db.add(version)
        db.flush()
        db.add(
            ShareGrant(
                handover_version_id=version.id,
                recipient_user_id=aisha.id,
                granted_by=maya.id,
            )
        )
        db.commit()
        case_id = case.id
        claim_id = claim.id
    finally:
        db.close()

    with TestClient(app) as client:
        _login_as(client, "aisha.khan@example.test")
        proj_view = client.get(f"/api/v1/recipient/cases/{case_id}")
        assert proj_view.status_code == 200
        body = proj_view.json()["transfer_packs"][0]["claims"][0]["body_text"]
        assert "Sup3rS3cr3tPass99" not in body
        assert "[REDACTED:CONNECTION_URI]" in body

        bundle_res = client.get(
            f"/api/v1/cases/{case_id}/exports/compliance-bundle.zip",
            params={"version_number": 1, "scope": "RECIPIENT_SAFE"},
        )
        assert bundle_res.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle_res.content), "r") as zf:
            snap_text = zf.read("snapshot.json").decode("utf-8")
            assert "Sup3rS3cr3tPass99" not in snap_text
            assert "[REDACTED:CONNECTION_URI]" in snap_text

    # Verify original stored DB claim row remains untouched
    db_check = SessionLocal()
    try:
        stored_claim = db_check.query(Claim).filter(Claim.id == claim_id).first()
        assert "Sup3rS3cr3tPass99" in stored_claim.body_text
    finally:
        db_check.close()


def test_r3_4d_claim_delegation_lifecycle_and_snapshot_immutability():
    db = SessionLocal()
    try:
        proj = db.query(Project).first()
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        aisha = db.query(User).filter(User.email == "aisha.khan@example.test").first()
        arjun = db.query(User).filter(User.email == "arjun.patel@example.test").first()
        kabir = db.query(User).filter(User.email == "kabir.singh@example.test").first()

        # Ensure arjun & kabir are active project members (Contributor = no restricted clearance by default)
        for member_user, role in [(arjun, ProjectRole.CONTRIBUTOR), (kabir, ProjectRole.CONTRIBUTOR)]:
            exists_m = (
                db.query(ProjectMembership)
                .filter(ProjectMembership.project_id == proj.id, ProjectMembership.user_id == member_user.id)
                .first()
            )
            if not exists_m:
                db.add(ProjectMembership(project_id=proj.id, user_id=member_user.id, role=role))

        outsider_email = f"del-out-{uuid.uuid4().hex[:6]}@example.test"
        outsider = User(
            id=uuid.uuid4(),
            email=outsider_email,
            display_name="Outside Engineer",
            password_hash=maya.password_hash,
            is_active=True,
        )
        db.add(outsider)
        db.flush()

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=946,
            title="Claim Delegation Lifecycle Case",
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
            name="Billing & Ops",
            component_area="billing",
            status=TransferPackStatus.APPROVED,
        )
        db.add(pack)
        db.flush()

        c_public = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.NEXT_ACTION,
            title="Rotate Stripe Webhook Endpoint",
            body_text="Verify webhook endpoint version compatibility after migration.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.HIGH,
        )
        c_revoke_test = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.OPERATIONAL_NOTE,
            title="Audit Billing Reconciliation Cron",
            body_text="Check nightly invoice reconciliation job.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.MEDIUM,
        )
        c_restricted = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.RISK,
            title="Restricted HSM Key Custody",
            body_text="HSM quorum requires two cleared officers.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.CRITICAL,
        )
        db.add_all([c_public, c_revoke_test, c_restricted])
        db.flush()

        src_rest = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.DOCUMENT_UPLOAD,
            name="Restricted Ops",
            external_id="restricted-ops",
        )
        db.add(src_rest)
        db.flush()
        rec_rest = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src_rest.id,
            source_type=SourceType.DOCUMENT_UPLOAD.value,
            record_type=SourceRecordType.DOCUMENT_SECTION,
            external_id="hsm-note",
            title="HSM Quorum Note",
            body="HSM quorum secret procedure",
            sensitivity=Sensitivity.RESTRICTED,
        )
        db.add(rec_rest)
        db.flush()
        db.add(
            ClaimEvidence(
                claim_id=c_restricted.id,
                source_record_id=rec_rest.id,
                evidence_type=EvidenceType.DIRECT_REFERENCE,
                excerpt="HSM quorum procedure",
                is_restricted=True,
            )
        )
        db.flush()

        snapshot, _, _ = build_canonical_snapshot_dict(
            db,
            case=case,
            version_number=1,
            approved_at=datetime.now(timezone.utc),
            approved_by_id=maya.id,
            approved_by_name=maya.display_name,
        )
        version = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=1,
            snapshot_json=snapshot,
            approved_by_id=maya.id,
            approved_at=datetime.now(timezone.utc),
            is_current=True,
        )
        db.add(version)
        db.flush()
        db.add(ShareGrant(handover_version_id=version.id, recipient_user_id=aisha.id, granted_by=maya.id))
        db.commit()

        case_id = case.id
        pack_id = pack.id
        version_id = version.id
        pub_claim_id = c_public.id
        rev_claim_id = c_revoke_test.id
        rest_claim_id = c_restricted.id
        arjun_id = arjun.id
        kabir_id = kabir.id
        aisha_id = aisha.id
        outsider_id = outsider.id
        original_snapshot = json.loads(json.dumps(version.snapshot_json))
        original_hash = version.snapshot_json["metadata"]["snapshot_hash"]
    finally:
        db.close()

    with TestClient(app) as client:
        # Lead assigns Pack to Aisha
        _login_as(client, "maya.sharma@example.test")
        assign_res = client.post(
            f"/api/v1/cases/{case_id}/responsibilities",
            json={"transfer_pack_id": str(pack_id), "assigned_user_id": str(aisha_id)},
        )
        assert assign_res.status_code == 201
        pack_assignment_id = assign_res.json()["id"]

        # Unauthorized actor (kabir) cannot delegate Aisha's pack claim
        _login_as(client, "kabir.singh@example.test")
        unauth_del = client.post(
            f"/api/v1/recipients/claims/{pub_claim_id}/delegate",
            json={"assigned_user_id": str(arjun_id)},
        )
        assert unauth_del.status_code == 403

        # Aisha accepts parent pack -> case becomes TRANSFERRED
        _login_as(client, "aisha.khan@example.test")
        acc_pack = client.post(f"/api/v1/responsibility-assignments/{pack_assignment_id}/accept")
        assert acc_pack.status_code == 200
        v1 = client.get(f"/api/v1/recipient/cases/{case_id}")
        assert v1.status_code == 200
        assert v1.json()["status"] == "TRANSFERRED"

        # Non-member target denied (403)
        non_mem = client.post(
            f"/api/v1/recipients/claims/{pub_claim_id}/delegate",
            json={"assigned_user_id": str(outsider_id)},
        )
        assert non_mem.status_code == 403

        # Uncleared member denied restricted claim delegation (403)
        rest_denied = client.post(
            f"/api/v1/recipients/claims/{rest_claim_id}/delegate",
            json={"assigned_user_id": str(arjun_id)},
        )
        assert rest_denied.status_code == 403

        # Aisha delegates c_public to Arjun -> pack becomes PARTIALLY_ACCEPTED, case PARTIALLY_ACKNOWLEDGED
        del_res = client.post(
            f"/api/v1/recipients/claims/{pub_claim_id}/delegate",
            json={"assigned_user_id": str(arjun_id), "note": "Handle Stripe webhook verification"},
        )
        assert del_res.status_code == 201, del_res.text
        delegation_id = del_res.json()["id"]
        assert del_res.json()["claim_id"] == str(pub_claim_id)

        # Duplicate active delegation blocked (400)
        dup_del = client.post(
            f"/api/v1/recipients/claims/{pub_claim_id}/delegate",
            json={"assigned_user_id": str(kabir_id)},
        )
        assert dup_del.status_code == 400

        v2 = client.get(f"/api/v1/recipient/cases/{case_id}").json()
        assert v2["status"] == "PARTIALLY_ACKNOWLEDGED"
        assert v2["transfer_packs"][0]["status"] == "PARTIALLY_ACCEPTED"
        assert len(v2["claim_assignments"]) == 1
        assert len(v2["eligible_delegates"]) >= 2

        # Wrong user cannot accept delegate assignment
        wrong_acc = client.post(f"/api/v1/responsibility-assignments/{delegation_id}/accept")
        assert wrong_acc.status_code == 400

        # Arjun views successor projection, declines first (keeps PARTIALLY_ACCEPTED / PARTIALLY_ACKNOWLEDGED), then accepts -> TRANSFERRED!
        _login_as(client, "arjun.patel@example.test")
        arjun_view = client.get(f"/api/v1/recipient/cases/{case_id}")
        assert arjun_view.status_code == 200
        assert any(ca["id"] == delegation_id for ca in arjun_view.json()["claim_assignments"])

        dec_res = client.post(
            f"/api/v1/responsibility-assignments/{delegation_id}/decline",
            json={"reason": "Waiting on staging Stripe key access"},
        )
        assert dec_res.status_code == 200
        assert dec_res.json()["status"] == "DECLINED"
        v3 = client.get(f"/api/v1/recipient/cases/{case_id}").json()
        assert v3["status"] == "PARTIALLY_ACKNOWLEDGED"
        assert v3["transfer_packs"][0]["status"] == "PARTIALLY_ACCEPTED"

        acc_del = client.post(f"/api/v1/responsibility-assignments/{delegation_id}/accept")
        assert acc_del.status_code == 200
        assert acc_del.json()["status"] == "ACCEPTED"
        v4 = client.get(f"/api/v1/recipient/cases/{case_id}").json()
        assert v4["status"] == "TRANSFERRED"
        assert v4["transfer_packs"][0]["status"] == "ACCEPTED"

        # Now Aisha delegates a second claim, case drops to PARTIALLY_ACKNOWLEDGED, then revokes -> restores TRANSFERRED & preserves revoked_at row!
        _login_as(client, "aisha.khan@example.test")
        del2 = client.post(
            f"/api/v1/recipients/claims/{rev_claim_id}/delegate",
            json={"assigned_user_id": str(arjun_id)},
        )
        assert del2.status_code == 201
        del2_id = del2.json()["id"]
        assert client.get(f"/api/v1/recipient/cases/{case_id}").json()["status"] == "PARTIALLY_ACKNOWLEDGED"

        rev_res = client.post(f"/api/v1/responsibility-assignments/{del2_id}/revoke")
        assert rev_res.status_code == 200
        assert rev_res.json()["revoked_at"] is not None
        v5 = client.get(f"/api/v1/recipient/cases/{case_id}").json()
        assert v5["status"] == "TRANSFERRED"
        assert v5["transfer_packs"][0]["status"] == "ACCEPTED"

    # Verify history row preserved & frozen snapshot untouched
    db_final = SessionLocal()
    try:
        revoked_row = db_final.query(ResponsibilityAssignment).filter(ResponsibilityAssignment.id == uuid.UUID(del2_id)).first()
        assert revoked_row is not None
        assert revoked_row.revoked_at is not None

        ver_final = db_final.query(HandoverVersion).filter(HandoverVersion.id == version_id).first()
        assert ver_final.snapshot_json["metadata"]["snapshot_hash"] == original_hash
        assert ver_final.snapshot_json == original_snapshot
    finally:
        db_final.close()
