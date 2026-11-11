"""Regression tests verifying core feature pipelines (GitHub mapping, re-sync, docs, timeline, auth refresh, LLM validation, and version stats)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.db.enums import JobStatus, JobType, ProcessingStatus, SourceRecordType
from app.db.session import SessionLocal
from app.integrations.github.mapper import map_commit, map_issue
from app.integrations.llm.gemini_provider import GeminiProvider
from app.integrations.llm.schemas.extraction import (
    CandidateTransferPack,
    EvidenceReference,
    EvidenceState,
    ExtractedWorkItem,
    ExtractionResult,
)
from app.integrations.llm.validators import validate_extraction_result
from app.modules.ingestion.models import SourceRecord
from app.modules.jobs.models import Job
from app.modules.jobs.service import enqueue_job
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource


def test_github_mapper_handles_pulls_and_null_users():
    # PR payload from /pulls lacks "pull_request" key and may have user=None and merged_at set
    pr_payload = {
        "number": 999,
        "title": "Fix auth race condition",
        "body": None,
        "user": None,
        "state": "closed",
        "merged_at": "2026-11-10T12:00:00Z",
        "html_url": "https://github.com/org/repo/pull/999",
        "created_at": "2026-11-10T10:00:00Z",
        "updated_at": "2026-11-10T12:00:00Z",
        "labels": [],
        "assignees": [],
        "milestone": None,
    }
    mapped_pr = map_issue(pr_payload, force_pr=True)
    assert mapped_pr["record_type"] == SourceRecordType.PR
    assert mapped_pr["state"] == "merged"
    assert mapped_pr["author_external_id"] is None

    commit_payload = {
        "sha": "deadbeef123",
        "author": None,
        "commit": {"author": None, "message": None},
        "html_url": "https://github.com/org/repo/commit/deadbeef123",
        "parents": [],
    }
    mapped_commit = map_commit(commit_payload)
    assert mapped_commit["record_type"] == SourceRecordType.COMMIT
    assert mapped_commit["external_id"] == "deadbeef123"


def test_gemini_extract_json_text_skips_thinking_parts_and_fences():
    parts = [
        {"thought": True, "text": "Let me analyze the prompt carefully..."},
        {"text": '```json\n{"transfer_packs": []}\n```'},
    ]
    extracted = GeminiProvider._extract_json_text(parts)
    assert extracted == '{"transfer_packs": []}'


def test_validator_marks_zero_evidence_unknown_and_keeps_partial_valid():
    valid_id = str(uuid.uuid4())
    fake_id = str(uuid.uuid4())
    sr = SourceRecord(
        id=uuid.UUID(valid_id),
        connected_source_id=uuid.uuid4(),
        source_type="GITHUB_REPO",
        record_type=SourceRecordType.PR,
        external_id="10",
        title="PR 10",
        body="Verified content line",
    )

    pack = CandidateTransferPack(
        name="Pack",
        description="Desc",
        work_items=[
            ExtractedWorkItem(
                title="Has valid and invalid",
                description="Partial valid",
                current_state="completed",
                evidence_state=EvidenceState.SUPPORTED,
                evidence=[
                    EvidenceReference(source_record_id=valid_id, excerpt="Verified content", relevance="ok"),
                    EvidenceReference(source_record_id=fake_id, excerpt="bad", relevance="bad"),
                ],
            ),
            ExtractedWorkItem(
                title="Zero evidence item",
                description="Hallucinated claim",
                current_state="completed",
                evidence_state=EvidenceState.SUPPORTED,
                evidence=[],
            ),
        ],
    )
    res, _ = validate_extraction_result(ExtractionResult(transfer_packs=[pack]), {valid_id}, {valid_id: sr})
    assert res.transfer_packs[0].work_items[0].evidence_state == EvidenceState.SUPPORTED
    assert len(res.transfer_packs[0].work_items[0].evidence) == 1
    assert res.transfer_packs[0].work_items[1].evidence_state == EvidenceState.UNKNOWN


def test_auth_refresh_timeline_dates_versions_and_resync():
    client = TestClient(app)

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_res.status_code == 200

    # 1. Verify POST /auth/refresh works (previously crashed with AttributeError on str UUID)
    refresh_res = client.post("/api/v1/auth/refresh")
    assert refresh_res.status_code == 200, f"auth/refresh failed: {refresh_res.text}"

    # 2. Verify Project list & Atlas project timeline with aware date_from/date_to
    ws_id = client.get("/api/v1/workspaces").json()[0]["id"]
    projects = client.get(f"/api/v1/workspaces/{ws_id}/projects").json()
    atlas = next(p for p in projects if p["slug"] == "atlas-platform")
    proj_id = atlas["id"]

    tl_res = client.get(
        f"/api/v1/projects/{proj_id}/timeline",
        params={"date_from": "2020-01-01T00:00:00Z", "date_to": "2030-12-31T23:59:59Z"},
    )
    assert tl_res.status_code == 200, f"timeline failed: {tl_res.text}"

    # 3. Verify CaseListResponse includes description and version stats are non-zero on Case #1
    cases = client.get(f"/api/v1/projects/{proj_id}/cases").json()
    case1 = next(c for c in cases if c["case_number"] == 1)
    assert "description" in case1 and case1["description"]

    versions = client.get(f"/api/v1/cases/{case1['id']}/versions").json()
    assert len(versions) >= 1
    assert versions[0]["total_packs"] >= 4
    assert versions[0]["total_claims"] >= 10

    # 4. Verify Document Upload with generic Windows/Chrome octet-stream MIME for .md succeeds (201)
    md_content = b"# Deployment Note\nRequires REDIS=false and PostgreSQL SSL.\n"
    upload_res = client.post(
        f"/api/v1/projects/{proj_id}/documents",
        files={"file": (f"test_note_{uuid.uuid4().hex[:6]}.md", md_content, "application/octet-stream")},
    )
    assert upload_res.status_code == 201, f"md octet-stream upload failed: {upload_res.text}"
    assert upload_res.json()["mime_type"] == "text/markdown"

    # 5. Verify Source re-sync works cleanly after COMPLETED or FAILED jobs without IntegrityError
    session = SessionLocal()
    try:
        src = session.query(ConnectedSource).filter(ConnectedSource.project_id == uuid.UUID(proj_id)).first()
        assert src is not None
        # Simulate a prior COMPLETED job with static idempotency key
        static_key = f"import-{src.id}"
        if not session.query(Job).filter(Job.idempotency_key == static_key).first():
            j = Job(
                job_type=JobType.SOURCE_IMPORT,
                status=JobStatus.FAILED,
                entity_type="connected_source",
                entity_id=src.id,
                idempotency_key=static_key,
                error_message="Simulated past error",
            )
            session.add(j)
            session.commit()
    finally:
        session.close()

    # Calling trigger_import twice must succeed cleanly (returning 202) and never crash with 500 IntegrityError
    res1 = client.post(f"/api/v1/sources/{src.id}/import")
    assert res1.status_code == 202, f"Sync #1 failed: {res1.text}"
    res2 = client.post(f"/api/v1/sources/{src.id}/import")
    assert res2.status_code == 202, f"Sync #2 failed: {res2.text}"


def test_auth_bearer_fallback_refresh_body_and_https_cookies():
    # Use a fresh cookie-less TestClient simulating third-party cookies blocked across Vercel -> Render
    login_client = TestClient(app)
    login_res = login_client.post(
        "/api/v1/auth/login",
        headers={"X-Forwarded-Proto": "https"},
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_res.status_code == 200
    body = login_res.json()
    assert body["access_token"]
    assert body["refresh_token"]

    # HTTPS proxy header must enforce SameSite=none; Secure even when APP_ENV=development
    set_cookie_hdrs = [v.lower() for k, v in login_res.headers.multi_items() if k.lower() == "set-cookie"]
    assert any("samesite=none" in h and "secure" in h for h in set_cookie_hdrs)

    # Fresh client WITHOUT any cookies succeeds via Authorization: Bearer
    bare_client = TestClient(app)
    me_no_cookie = bare_client.get("/api/v1/auth/me")
    assert me_no_cookie.status_code == 401

    me_bearer = bare_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me_bearer.status_code == 200
    assert me_bearer.json()["email"] == "maya.sharma@example.test"

    # Cookie-less refresh via JSON body returns fresh access_token cleanly
    ref_res = bare_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": body["refresh_token"]},
    )
    assert ref_res.status_code == 200
    new_access = ref_res.json()["access_token"]
    assert new_access

    me_refreshed = bare_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me_refreshed.status_code == 200
