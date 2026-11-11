"""Phase 7: Full end-to-end 6-gap lifecycle verification through HTTP endpoints and workers."""

from __future__ import annotations

import time
import uuid

import httpx
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.enums import (
    ProjectRole,
    Sensitivity,
    SourceRecordType,
    SourceType,
)
from app.db.session import SessionLocal
from app.integrations.github.client import GitHubClient
from app.modules.evidence.models import ClaimEvidence
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project, ProjectMembership
from app.modules.sources.service import cleanup_duplicate_github_records
from app.modules.transfer_packs.models import Claim
from app.modules.workspaces.models import User


client = TestClient(app=__import__("app.main", fromlist=["app"]).app)


def _login(email: str) -> dict:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "handoffscope-dev-2026"},
    )
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()


def _wait_for_job(job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = client.get(f"/api/v1/jobs/{job_id}")
        if res.status_code == 200:
            data = res.json()
            if data["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                return data
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish within {timeout}s")


def test_full_six_gap_end_to_end_pipeline(monkeypatch):
    # Ensure explicit mock LLM mode for deterministic E2E reconstruction
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")

    session = SessionLocal()
    try:
        maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        kabir = session.query(User).filter(User.email == "kabir.singh@example.test").first()
        arjun = session.query(User).filter(User.email == "arjun.patel@example.test").first()
        aisha = session.query(User).filter(User.email == "aisha.khan@example.test").first()
        assert maya and kabir and arjun and aisha

        seed_proj = session.query(Project).filter(Project.slug == "atlas-platform").first()
        assert seed_proj is not None

        # Step 1: Hermetic project creation via API + role assignments
        maya_login = _login("maya.sharma@example.test")
        assert "case.approve_override" in maya_login["user"].get("capabilities", [])

        proj_res = client.post(
            f"/api/v1/workspaces/{seed_proj.workspace_id}/projects",
            json={
                "name": "Phase 7 Full E2E Service",
                "slug": f"phase7-e2e-{uuid.uuid4().hex[:8]}",
                "description": "End-to-end 6-gap handover pipeline verification",
            },
        )
        assert proj_res.status_code == 201, proj_res.text
        proj_id = uuid.UUID(proj_res.json()["id"])

        # Add project roles explicitly for hermetic RBAC
        session.add_all([
            ProjectMembership(project_id=proj_id, user_id=kabir.id, role=ProjectRole.REVIEWER),
            ProjectMembership(project_id=proj_id, user_id=arjun.id, role=ProjectRole.CONTRIBUTOR),
            ProjectMembership(project_id=proj_id, user_id=aisha.id, role=ProjectRole.CONTRIBUTOR),
        ])
        session.commit()

        # Step 2: Connect GitHub source + plant a historical duplicate PR-as-ISSUE #42
        src_res = client.post(
            f"/api/v1/projects/{proj_id}/sources",
            json={
                "source_type": "GITHUB_REPO",
                "name": "acme/payment-core",
                "external_id": "acme/payment-core",
                "config": {"owner": "acme", "repo": "payment-core", "access_token": "mock-tok"},
            },
        )
        assert src_res.status_code == 201, src_res.text
        source_id = uuid.UUID(src_res.json()["id"])

        hist_dup_issue = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=source_id,
            source_type=SourceType.GITHUB_REPO,
            record_type=SourceRecordType.ISSUE,
            external_id="42",
            title="Switch Redis session lock to token bucket",
            body="Historical duplicate PR-as-ISSUE payload for #42.",
            state="closed",
            url="https://github.com/acme/payment-core/pull/42",
            metadata_json={"is_pull_request": True},
        )
        restricted_rec = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=source_id,
            source_type=SourceType.GITHUB_REPO,
            record_type=SourceRecordType.COMMIT,
            external_id="sec-999",
            title="Production KMS Vault Passphrase Setup",
            body="VAULT_PASSPHRASE=kms-prod-rotation-999 must stay confidential.",
            author_name="arjun",
            sensitivity=Sensitivity.RESTRICTED,
        )
        session.add_all([hist_dup_issue, restricted_rec])
        session.commit()

        # Mock GitHub remote fetch
        monkeypatch.setattr(
            GitHubClient,
            "list_issues",
            lambda self, o, r: [
                {
                    "number": 7,
                    "title": "ADR: Idempotency Key TTL Policy",
                    "body": "Decision: Store idempotency keys in Redis for 24 hours because payment retries occur across regions.",
                    "state": "open",
                    "html_url": "https://github.com/acme/payment-core/issues/7",
                    "user": {"login": "arjun"},
                    "labels": [{"name": "adr"}],
                    "assignees": [],
                    "created_at": "2026-09-01T10:00:00Z",
                    "updated_at": "2026-09-02T10:00:00Z",
                },
                {
                    "number": 42,
                    "title": "Switch Redis session lock to token bucket",
                    "body": "PR #42 payload returned by /issues must be skipped.",
                    "state": "closed",
                    "html_url": "https://github.com/acme/payment-core/pull/42",
                    "pull_request": {"url": "https://api.github.com/repos/acme/payment-core/pulls/42"},
                    "user": {"login": "arjun"},
                    "labels": [],
                    "assignees": [],
                    "created_at": "2026-10-01T10:00:00Z",
                    "updated_at": "2026-10-02T10:00:00Z",
                },
            ],
        )
        monkeypatch.setattr(
            GitHubClient,
            "list_pulls",
            lambda self, o, r: [
                {
                    "number": 42,
                    "title": "Switch Redis session lock to token bucket",
                    "body": "Decision: Set token bucket TTL to 300 seconds in Redis db 2 for rate limiting.",
                    "state": "closed",
                    "merged_at": "2026-10-02T11:00:00Z",
                    "html_url": "https://github.com/acme/payment-core/pull/42",
                    "user": {"login": "arjun"},
                    "labels": [],
                    "assignees": [],
                    "created_at": "2026-10-01T10:00:00Z",
                    "updated_at": "2026-10-02T11:00:00Z",
                }
            ],
        )
        monkeypatch.setattr(GitHubClient, "list_issue_comments", lambda self, o, r, n: [])
        monkeypatch.setattr(GitHubClient, "list_pull_reviews", lambda self, o, r, n: [])
        monkeypatch.setattr(GitHubClient, "list_pull_review_comments", lambda self, o, r, n: [])
        monkeypatch.setattr(GitHubClient, "list_commits", lambda self, o, r: [])

        imp_res = client.post(f"/api/v1/sources/{source_id}/import")
        assert imp_res.status_code in (200, 202), imp_res.text
        imp_job = _wait_for_job(imp_res.json()["job_id"])
        assert imp_job["status"] == "COMPLETED"

        # Step 3: Verify sync telemetry on source listing (no double-import + skipped PR counted)
        list_src_res = client.get(f"/api/v1/projects/{proj_id}/sources")
        assert list_src_res.status_code == 200
        src_entry = list_src_res.json()[0]
        assert src_entry["last_successful_sync_at"] is not None
        assert src_entry["last_sync_run"]["status"] == "COMPLETED"
        assert src_entry["last_sync_run"]["records_skipped"] >= 1

        # Step 4: Upload Markdown runbook document & wait for parsing job
        runbook_md = (
            b"# Payment Core Operations Runbook\n\n"
            b"## Database Failover Procedure\n"
            b"When primary Postgres stops responding, promote replica using `pg_ctl promote` within 120 seconds.\n\n"
            b"## Architecture Decision Rationale\n"
            b"We decided to isolate settlement queues because idempotency guarantees prevent double-charges.\n"
        )
        doc_res = client.post(
            f"/api/v1/projects/{proj_id}/documents",
            files={"file": ("payment_runbook.md", runbook_md, "text/markdown")},
        )
        assert doc_res.status_code == 201, doc_res.text
        doc_id = doc_res.json()["id"]

        deadline = time.monotonic() + 10.0
        doc_done = False
        while time.monotonic() < deadline:
            dlist = client.get(f"/api/v1/projects/{proj_id}/documents").json()
            cur_doc = next((d for d in dlist if d["id"] == doc_id), None)
            if cur_doc and cur_doc["processing_status"] == "COMPLETED":
                doc_done = True
                break
            time.sleep(0.05)
        assert doc_done, "Uploaded markdown document did not complete parsing"

        # Step 5: Create Handover Case + Participants via API
        case_res = client.post(
            f"/api/v1/projects/{proj_id}/cases",
            json={
                "title": "Arjun Payment Core Transition",
                "description": "E2E transition case",
                "transition_type": "PLANNED_DEPARTURE",
            },
        )
        assert case_res.status_code == 201, case_res.text
        case_id = uuid.UUID(case_res.json()["id"])

        for u_obj, role in [
            (kabir, "REVIEWER"),
            (arjun, "DEPARTING"),
            (aisha, "RECIPIENT"),
        ]:
            p_res = client.post(
                f"/api/v1/cases/{case_id}/participants",
                json={"user_id": str(u_obj.id), "role": role},
            )
            assert p_res.status_code == 201, p_res.text

        # Step 6: Run Reconstruction -> explicit mock mode + doc & repo claims
        rec_res = client.post(f"/api/v1/cases/{case_id}/reconstruct")
        assert rec_res.status_code == 200, rec_res.text
        rec_data = rec_res.json()
        assert rec_data["provider_mode"] == "mock"
        assert rec_data["fallback_used"] is False
        assert rec_data["claims_created"] >= 2

        claims_list = client.get(f"/api/v1/cases/{case_id}/claims").json()
        assert len(claims_list) >= 2
        packs_list = client.get(f"/api/v1/cases/{case_id}/transfer-packs").json()
        assert len(packs_list) >= 1

        # Attach restricted evidence onto first claim to verify redaction later
        first_claim_id = uuid.UUID(claims_list[0]["id"])
        session.add(
            ClaimEvidence(
                id=uuid.uuid4(),
                claim_id=first_claim_id,
                source_record_id=restricted_rec.id,
                excerpt="VAULT_PASSPHRASE=kms-prod-rotation-999",
                locator="commit:sec-999",
                is_restricted=True,
            )
        )
        session.commit()

        # Step 7: Successor (Aisha) asks standalone, linked, restricted, critical, and non-critical questions
        _login("aisha.khan@example.test")

        def _ask(payload: dict) -> dict:
            r = client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={"case_id": str(case_id), **payload},
            )
            assert r.status_code == 201, r.text
            return r.json()

        q_standalone = _ask({
            "question_text": "What failover command handles Postgres replica promotion?",
            "why_it_matters": "Needed during database outages.",
            "priority": "MEDIUM",
        })
        q_linked = _ask({
            "question_text": "Clarify token bucket TTL for Redis rate limiting?",
            "claim_id": str(first_claim_id),
            "priority": "MEDIUM",
        })
        q_restricted = _ask({
            "question_text": "What is the exact kms-prod-rotation vault passphrase?",
            "priority": "LOW",
        })
        q_critical = _ask({
            "question_text": "Has the critical security credential exposure been rotated?",
            "priority": "HIGH",
        })
        q_non_crit = _ask({
            "question_text": "Which Grafana dashboard shows weekly latency percentiles?",
            "priority": "LOW",
        })

        # Step 8: AI Draft Answer on q_standalone -> ALWAYS PENDING_REVIEW + cites permitted record
        ai_res = client.post(f"/api/v1/questions/{q_standalone['id']}/generate-answer")
        assert ai_res.status_code == 200, ai_res.text
        ai_q = ai_res.json()
        assert ai_q["status"] == "ANSWERED"  # Never RESOLVED automatically
        ai_resp = ai_q["responses"][-1]
        assert ai_resp["is_ai_generated"] is True
        assert ai_resp["review_state"] == "PENDING_REVIEW"
        assert ai_resp["answer_status"] == "answered"
        assert len(ai_resp["evidence_references"]) >= 1

        # Citation drilldown allowed for cited permitted record, 403 for restricted record
        cited_id = ai_resp["evidence_references"][0]["source_id"]
        assert client.get(f"/api/v1/cases/{case_id}/sources/records/{cited_id}").status_code == 200
        assert client.get(f"/api/v1/cases/{case_id}/sources/records/{restricted_rec.id}").status_code == 403

        # Restricted prompt check: insufficient + zero secret exposure
        rest_ai = client.post(f"/api/v1/questions/{q_restricted['id']}/generate-answer").json()
        assert rest_ai["responses"][-1]["answer_status"] == "insufficient"
        assert "kms-prod-rotation-999" not in rest_ai["responses"][-1]["response_text"]

        # Step 9: Departing engineer (Arjun) answers linked & critical questions
        _login("arjun.patel@example.test")
        client.post(
            f"/api/v1/questions/{q_linked['id']}/responses",
            json={"response_text": "Token bucket TTL is strictly 300s in Redis db 2."},
        )
        client.post(
            f"/api/v1/questions/{q_critical['id']}/responses",
            json={"response_text": "All KMS secrets were rotated before handover."},
        )

        # Step 10: Reviewer (Kabir) accepts AI draft (promotes standalone -> OPERATIONAL_NOTE) & accepts linked clarification
        _login("kabir.singh@example.test")
        rev_standalone = client.patch(
            f"/api/v1/questions/{q_standalone['id']}/review",
            json={"action": "accept"},
        )
        assert rev_standalone.status_code == 200, rev_standalone.text
        assert rev_standalone.json()["status"] == "RESOLVED"
        assert rev_standalone.json()["promotion_result"]["status"] == "promoted_operational_note"
        promoted_claim_id = rev_standalone.json()["promotion_result"]["claim_id"]

        # Re-accepting / idempotency guard -> only 1 claim with origin_question_id
        session.expire_all()
        assert (
            session.query(Claim).filter(Claim.origin_question_id == uuid.UUID(q_standalone["id"])).count()
            == 1
        )
        promoted_claim_obj = session.query(Claim).filter(Claim.id == uuid.UUID(promoted_claim_id)).first()
        assert promoted_claim_obj.claim_type.value == "OPERATIONAL_NOTE"

        # Accept linked question -> updates linked claim without overwriting original_body_text
        orig_first_body = claims_list[0]["body_text"]
        rev_linked = client.patch(
            f"/api/v1/questions/{q_linked['id']}/review",
            json={"action": "accept"},
        )
        assert rev_linked.status_code == 200
        assert rev_linked.json()["promotion_result"]["status"] == "linked_claim_updated"
        session.expire_all()
        updated_first_claim = session.query(Claim).filter(Claim.id == first_claim_id).first()
        assert updated_first_claim.original_body_text == orig_first_body
        assert "300s in Redis db 2" in updated_first_claim.body_text

        # Resolve q_restricted via human accept (we'll keep q_critical & q_non_crit open first to verify critical block!)
        # Actually resolve q_restricted so only q_critical + q_non_crit remain unresolved
        client.patch(
            f"/api/v1/questions/{q_restricted['id']}/review",
            json={"action": "amend", "amended_text": "Redacted for general staff; vault managed by Infra Lead."},
        )

        # Accept all claims (including promoted & restricted-amend claims) + approve all packs
        all_claims_now = client.get(f"/api/v1/cases/{case_id}/claims").json()
        for c_item in all_claims_now:
            r = client.patch(f"/api/v1/claims/{c_item['id']}/review", json={"action": "accept"})
            assert r.status_code == 200, r.text
        for p_item in client.get(f"/api/v1/cases/{case_id}/transfer-packs").json():
            if p_item["status"] == "DRAFT":
                client.post(f"/api/v1/transfer-packs/{p_item['id']}/status", json={"status": "IN_REVIEW"})
            if p_item["status"] != "APPROVED":
                client.post(f"/api/v1/transfer-packs/{p_item['id']}/status", json={"status": "APPROVED"})

        # Step 11: Critical Blocker Check -> even Lead CANNOT override while q_critical is unresolved!
        _login("maya.sharma@example.test")
        rq_crit = client.get(f"/api/v1/cases/{case_id}/review-queue").json()
        assert rq_crit["can_approve"] is False
        assert rq_crit["can_override"] is False
        crit_attempt = client.post(
            f"/api/v1/cases/{case_id}/versions",
            json={"override_blockers": True, "override_reason": "Trying to bypass critical security blocker"},
        )
        assert crit_attempt.status_code == 400
        assert "critical" in crit_attempt.json()["detail"].lower()

        # Resolve q_critical now (Reviewer accepts Arjun's answer + accepts promoted critical claim)
        _login("kabir.singh@example.test")
        rev_crit = client.patch(f"/api/v1/questions/{q_critical['id']}/review", json={"action": "accept"})
        assert rev_crit.status_code == 200
        crit_promoted_id = rev_crit.json()["promotion_result"]["claim_id"]
        assert client.patch(f"/api/v1/claims/{crit_promoted_id}/review", json={"action": "accept"}).status_code == 200

        # Step 12: Non-critical blocker (q_non_crit) -> Reviewer blocked & 403 override; Lead approves with override!
        rq_kabir = client.get(f"/api/v1/cases/{case_id}/review-queue").json()
        assert rq_kabir["can_approve"] is False
        assert rq_kabir["can_override"] is False
        assert (
            client.post(
                f"/api/v1/cases/{case_id}/versions",
                json={"override_blockers": True, "override_reason": "Reviewer override must be forbidden"},
            ).status_code
            == 403
        )

        _login("maya.sharma@example.test")
        rq_maya = client.get(f"/api/v1/cases/{case_id}/review-queue").json()
        assert rq_maya["can_approve"] is False
        assert rq_maya["can_override"] is True

        # Short reason fails
        assert (
            client.post(
                f"/api/v1/cases/{case_id}/versions",
                json={"override_blockers": True, "override_reason": "short"},
            ).status_code
            == 400
        )

        # Valid Lead override succeeds!
        v1_res = client.post(
            f"/api/v1/cases/{case_id}/versions",
            json={
                "override_blockers": True,
                "override_reason": "Approved with Grafana dashboard question deferred to onboarding week 1.",
            },
        )
        assert v1_res.status_code == 201, v1_res.text
        v1 = v1_res.json()
        assert v1["version_number"] == 1
        snap = v1["snapshot_json"]
        assert snap["metadata"]["schema_version"] >= 2
        assert len(snap["metadata"]["snapshot_hash"]) == 64
        assert snap["override_metadata"]["overridden"] is True
        frozen_first_body = snap["transfer_packs"][0]["claims"][0]["body_text"]
        frozen_first_id = snap["transfer_packs"][0]["claims"][0]["id"]

        # Step 13: Mutate live claim AFTER v1 approval + re-run reconstruction -> MUST NOT mutate frozen v1!
        mut_res = client.patch(
            f"/api/v1/claims/{frozen_first_id}",
            json={"body_text": "LIVE_POST_APPROVAL_MUTATION_SHOULD_NOT_LEAK"},
        )
        assert mut_res.status_code == 200
        # Also run reconstruction again in background draft state
        assert client.post(f"/api/v1/cases/{case_id}/reconstruct").status_code == 200

        # Step 14: Share Version 1 with Successor (Aisha)
        share_res = client.post(
            f"/api/v1/versions/{v1['id']}/share",
            json={"recipient_user_id": str(aisha.id)},
        )
        assert share_res.status_code == 201, share_res.text

        # Step 15: Aisha views Continuation View -> sees FROZEN Version 1 + REDACTED restricted evidence!
        _login("aisha.khan@example.test")
        succ_res = client.get(f"/api/v1/recipient/cases/{case_id}")
        assert succ_res.status_code == 200, succ_res.text
        succ_data = succ_res.json()
        assert succ_data["current_version_number"] == 1
        assert succ_data["is_snapshot_backed"] is True
        assert succ_data["snapshot_mode"] == "frozen_snapshot"
        assert succ_data["snapshot_schema_version"] >= 2
        assert any(u["type"].startswith("OVERRIDDEN_") for u in succ_data["unfinished_items"])

        projected_claims = [c for p in succ_data["transfer_packs"] for c in p["claims"]]
        matched_proj = next(c for c in projected_claims if c["id"] == frozen_first_id)
        assert matched_proj["body_text"] == frozen_first_body
        assert "LIVE_POST_APPROVAL_MUTATION_SHOULD_NOT_LEAK" not in matched_proj["body_text"]
        # Restricted evidence attached to first_claim_id redacted cleanly
        restricted_proj = next(c for c in projected_claims if c["id"] == str(first_claim_id))
        assert restricted_proj["is_restricted_withheld"] is True
        assert all("kms-prod-rotation-999" not in snip for snip in restricted_proj.get("evidence_snippets", []))

        # Step 16: Successor acknowledges handover independently of frozen content
        ack_res = client.post(f"/api/v1/recipient/cases/{case_id}/acknowledge")
        assert ack_res.status_code == 200, ack_res.text
        succ_after_ack = client.get(f"/api/v1/recipient/cases/{case_id}").json()
        assert succ_after_ack["is_acknowledged"] is True
        assert succ_after_ack["current_version_number"] == 1
        assert succ_after_ack["snapshot_schema_version"] == succ_data["snapshot_schema_version"]

        # Step 17: Deduplicate historical duplicate PR-as-ISSUE #42 (dry-run -> apply -> verify)
        dry_dedup = cleanup_duplicate_github_records(
            session, actor_id=maya.id, project_id=proj_id, dry_run=True
        )
        assert dry_dedup["safe_duplicate_count"] == 1
        applied_dedup = cleanup_duplicate_github_records(
            session, actor_id=maya.id, project_id=proj_id, dry_run=False
        )
        assert applied_dedup["duplicates_deleted"] == 1
        session.expire_all()
        assert (
            session.query(SourceRecord)
            .filter(SourceRecord.connected_source_id == source_id, SourceRecord.external_id == "42")
            .count()
            == 1
        )

        # Step 18: Local freshness endpoint makes ZERO outbound calls & reports local semantics
        _login("maya.sharma@example.test")
        outbound = []
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: outbound.append(a))
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: outbound.append(a))
        fresh_res = client.post(
            f"/api/v1/sources/{source_id}/refresh",
            json={"simulate_modification": False},
        )
        assert fresh_res.status_code == 200, fresh_res.text
        assert fresh_res.json()["is_local_only"] is True
        assert fresh_res.json()["freshness_basis"] == "local_timestamps"
        assert outbound == []
    finally:
        session.close()
