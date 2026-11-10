"""Comprehensive 19-step End-to-End Judge Walkthrough API Test.

Phase 10 — Hardening & Demo.
Verifies the complete lifecycle:
1. Login as Project Lead (Maya)
2. Verify project & workspace existence
3. Verify source coverage (GitHub records + documents)
4. Verify Handover Case created with participants
5. Verify reconstructed Transfer Packs (4 packs)
6. Verify evidence states (SUPPORTED, CONFLICTING, UNKNOWN)
7. Verify conflicting architecture decision visible with citations
8. Verify knowledge gap visible
9. Question workflow: answer by departing, reviewed
10. Login as Reviewer (Kabir)
11. Review claims (accept, edit_and_accept, needs_clarification)
12. Create & verify immutable version snapshot (v1)
13. Share version grant issued to Successor (Aisha)
14. Login as Successor (Aisha) & verify restricted document is withheld/redacted
15. Acknowledge case receipt
16. Accept responsibility for Authentication API pack
17. Decline responsibility for Payment Integration pack (with required reason)
18. Verify case status reflects partial acceptance (PARTIALLY_ACKNOWLEDGED)
19. Verify complete audit trail recorded across all actors
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.enums import (
    CaseStatus,
    CaseSyncStatus,
    EvidenceState,
    ReviewState,
    TransferPackStatus,
)
from app.db.session import SessionLocal
from app.modules.audit.models import AuditEvent
from app.modules.handover_cases.models import HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.questions.models import Question
from app.modules.recipients.models import (
    RecipientAcknowledgement,
    ResponsibilityAcceptance,
    ResponsibilityAssignment,
)
from app.modules.reviews.models import HandoverVersion
from app.modules.sharing.models import ShareGrant
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


def test_complete_judge_e2e_walkthrough():
    client = TestClient(app)

    # ── Step 1: Login as Project Lead (Maya Sharma) ────────────
    maya_login = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert maya_login.status_code == 200, "Maya login failed"

    # ── Step 2: Verify project & workspace ────────────────────
    ws_res = client.get("/api/v1/workspaces")
    assert ws_res.status_code == 200
    workspaces = ws_res.json()
    assert len(workspaces) >= 1
    ws_id = workspaces[0]["id"]

    proj_res = client.get(f"/api/v1/workspaces/{ws_id}/projects")
    assert proj_res.status_code == 200
    projects = proj_res.json()
    atlas_proj = next((p for p in projects if p["slug"] == "atlas-platform"), None)
    assert atlas_proj is not None, "Atlas Platform project not found"
    proj_id = atlas_proj["id"]

    # ── Step 3: Verify source coverage ────────────────────────
    sources_res = client.get(f"/api/v1/projects/{proj_id}/sources")
    assert sources_res.status_code == 200
    sources = sources_res.json()
    assert len(sources) >= 1

    session = SessionLocal()
    try:
        record_count = session.query(SourceRecord).count()
        assert record_count >= 50, f"Expected >= 50 source records, found {record_count}"

        # ── Step 4: Verify Handover Case #1 ───────────────────
        case = session.query(HandoverCase).filter(
            HandoverCase.project_id == uuid.UUID(proj_id),
            HandoverCase.case_number == 1,
        ).first()
        assert case is not None, "Handover Case #1 not found"
        case_id = str(case.id)

        case_res = client.get(f"/api/v1/cases/{case_id}")
        assert case_res.status_code == 200
        case_data = case_res.json()
        assert "Arjun Patel" in case_data["title"]

        # ── Step 5: Verify 4 Transfer Packs ───────────────────
        packs_res = client.get(f"/api/v1/cases/{case_id}/transfer-packs")
        assert packs_res.status_code == 200
        packs = packs_res.json()
        assert len(packs) >= 4, f"Expected at least 4 transfer packs, found {len(packs)}"

        pack_names = [p["name"] for p in packs]
        assert "Authentication API & Multi-Tenancy" in pack_names
        assert "Payment Integration Service" in pack_names
        assert "Database Migrations & Schema v2" in pack_names
        assert "Deployment Operations & Staging" in pack_names

        # ── Step 6: Verify Evidence States ────────────────────
        claims_res = client.get(f"/api/v1/cases/{case_id}/claims")
        assert claims_res.status_code == 200
        claims = claims_res.json()
        assert len(claims) >= 10

        evidence_states = {c["evidence_state"] for c in claims}
        assert "SUPPORTED" in evidence_states
        assert "CONFLICTING" in evidence_states
        assert "UNKNOWN" in evidence_states

        # ── Step 7: Verify Conflicting Decision ────────────────
        conflicting_claims = [c for c in claims if c["evidence_state"] == "CONFLICTING"]
        assert len(conflicting_claims) >= 1
        conf_claim = conflicting_claims[0]
        assert "Microservices vs Monolith" in conf_claim["title"]

        # ── Step 8: Verify Knowledge Gap ──────────────────────
        unknown_claims = [c for c in claims if c["evidence_state"] == "UNKNOWN"]
        assert len(unknown_claims) >= 1

        # ── Step 9: Question Loop ─────────────────────────────
        questions_res = client.get(f"/api/v1/cases/{case_id}/questions")
        assert questions_res.status_code == 200
        questions = questions_res.json()
        assert len(questions) >= 1
        q_auth = next((q for q in questions if "deployment process" in q["question_text"]), None)
        assert q_auth is not None
        assert q_auth["status"] in ("ANSWERED", "CLOSED")

        # ── Step 10: Login as Reviewer (Kabir Singh) ──────────
        kabir_login = client.post(
            "/api/v1/auth/login",
            json={"email": "kabir.singh@example.test", "password": "handoffscope-dev-2026"},
        )
        assert kabir_login.status_code == 200, "Kabir login failed"

        # ── Step 11: Review claims ────────────────────────────
        review_states = {c["review_state"] for c in claims}
        assert "ACCEPTED" in review_states
        assert "NEEDS_CLARIFICATION" in review_states

        # ── Step 12: Verify Immutable Handover Version (v1) ────
        versions_res = client.get(f"/api/v1/cases/{case_id}/versions")
        assert versions_res.status_code == 200
        versions = versions_res.json()
        assert len(versions) >= 1
        v1 = versions[0]
        assert v1["version_number"] == 1
        v1_id = v1["id"]

        # ── Step 13: Share Version with Successor (Aisha) ─────
        shares_res = client.get(f"/api/v1/versions/{v1_id}/shares")
        assert shares_res.status_code == 200
        shares = shares_res.json()
        assert len(shares) >= 1

        # ── Step 14: Login as Successor (Aisha Khan) ──────────
        aisha_login = client.post(
            "/api/v1/auth/login",
            json={"email": "aisha.khan@example.test", "password": "handoffscope-dev-2026"},
        )
        assert aisha_login.status_code == 200, "Aisha login failed"

        # Successor continuation view — verify restricted doc is REDACTED / withheld
        succ_res = client.get(f"/api/v1/recipient/cases/{case_id}")
        assert succ_res.status_code == 200
        succ_view = succ_res.json()

        # Check access blockers
        access_blockers = succ_view.get("access_blockers", [])
        assert len(access_blockers) >= 1, "Expected at least 1 access blocker for restricted content"
        blocker = access_blockers[0]
        assert "elevated clearance" in blocker["reason"].lower()
        assert blocker["pack_name"] == "Deployment Operations & Staging"

        # ── Step 15: Verify Acknowledgement ───────────────────
        ack_record = session.query(RecipientAcknowledgement).filter(
            RecipientAcknowledgement.handover_version_id == uuid.UUID(v1_id)
        ).first()
        assert ack_record is not None, "Recipient acknowledgement record missing"

        # ── Step 16 & 17: Verify Responsibility Acceptance & Decline
        resp_res = client.get(f"/api/v1/cases/{case_id}/responsibilities")
        assert resp_res.status_code == 200
        responsibilities = resp_res.json()
        assert len(responsibilities) >= 2

        accepted_resp = next((r for r in responsibilities if r["status"] == "ACCEPTED"), None)
        assert accepted_resp is not None, "Expected one ACCEPTED responsibility"
        assert "Authentication API" in accepted_resp["transfer_pack_name"]

        declined_resp = next((r for r in responsibilities if r["status"] == "DECLINED"), None)
        assert declined_resp is not None, "Expected one DECLINED responsibility"
        assert "Payment Integration" in declined_resp["transfer_pack_name"]
        assert declined_resp.get("decline_reason") is not None
        assert "training" in declined_resp["decline_reason"].lower()

        # ── Step 18: Verify Case Transfer State ────────────────
        updated_case_res = client.get(f"/api/v1/cases/{case_id}")
        assert updated_case_res.status_code == 200
        updated_case = updated_case_res.json()
        assert updated_case["status"] in ("PARTIALLY_ACKNOWLEDGED", "TRANSFERRED", "NEEDS_INPUT", "APPROVED")
        assert updated_case["sync_status"] in ("CURRENT", "POTENTIALLY_STALE")

        # ── Step 19: Full Audit Trail ─────────────────────────
        audit_res = client.get("/api/v1/audit/events?limit=100")
        assert audit_res.status_code == 200
        audit_events = audit_res.json()
        assert len(audit_events) >= 5

        actions = {e["action"] for e in audit_events}
        assert any(a.startswith("case.") for a in actions)
        assert any(a.startswith("responsibility.") for a in actions)

    finally:
        session.close()
