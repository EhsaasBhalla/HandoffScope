"""Phase 3 (Gap 5) tests: authoritative preflight, critical/non-critical blockers, RBAC, and Lead override."""

from __future__ import annotations

import uuid
from fastapi.testclient import TestClient
from sqlalchemy import func

from app.main import app
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    EvidenceState,
    Priority,
    QuestionResponseReviewState,
    QuestionStatus,
    ReviewState,
    TransferPackStatus,
    TransitionType,
)
from app.db.session import SessionLocal
from app.modules.audit.models import AuditEvent
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.questions.models import Question, QuestionResponse
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


client = TestClient(app)


def test_preflight_guardrails_critical_blocks_and_lead_override():
    session = SessionLocal()
    try:
        maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        kabir = session.query(User).filter(User.email == "kabir.singh@example.test").first()
        arjun = session.query(User).filter(User.email == "arjun.patel@example.test").first()
        aisha = session.query(User).filter(User.email == "aisha.khan@example.test").first()
        assert maya and kabir and arjun and aisha

        project_id = maya.workspace_memberships[0].workspace.projects[0].id
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == project_id).scalar() or 0
        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=project_id,
            case_number=max_num + 1,
            title=f"Gap 5 Guardrail Case #{max_num + 1}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.UNDER_REVIEW,
            created_by_id=maya.id,
        )
        session.add(case)
        session.flush()
        session.add_all([
            CaseParticipant(case_id=case.id, user_id=arjun.id, role=CaseParticipantRole.DEPARTING),
            CaseParticipant(case_id=case.id, user_id=kabir.id, role=CaseParticipantRole.REVIEWER),
            CaseParticipant(case_id=case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT),
        ])

        pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Service Runbooks",
            status=TransferPackStatus.READY_FOR_REVIEW,
        )
        session.add(pack)
        session.flush()

        claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.OPERATIONAL_NOTE,
            title="Service Startup Flags",
            body_text="Requires PORT=8000.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.MEDIUM,
        )
        session.add(claim)
        session.flush()

        # Question 1: Non-critical minor clarification question (no critical security terms)
        q_minor = Question(
            id=uuid.uuid4(),
            case_id=case.id,
            transfer_pack_id=pack.id,
            question_text="Should the onboarding readme include team Slack channel names?",
            why_it_matters="Helps new member find general discussion channels.",
            priority=Priority.LOW,
            status=QuestionStatus.OPEN,
            created_by_id=aisha.id,
        )
        # Question 2: Critical security question
        q_critical = Question(
            id=uuid.uuid4(),
            case_id=case.id,
            transfer_pack_id=pack.id,
            question_text="Who rotates production KMS database credentials?",
            why_it_matters="Critical security and production access dependency.",
            priority=Priority.CRITICAL,
            status=QuestionStatus.OPEN,
            created_by_id=aisha.id,
        )
        session.add_all([q_minor, q_critical])
        session.commit()

        # 0. Verify /auth/me returns server-side capabilities cleanly
        client.post("/api/v1/auth/login", json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"})
        me_maya = client.get("/api/v1/auth/me").json()
        assert "case.approve_override" in me_maya["capabilities"]

        # 1. Critical question blocks both ordinary approval AND Lead override
        rq_crit = client.get(f"/api/v1/cases/{case.id}/review-queue").json()
        assert rq_crit["can_approve"] is False
        assert rq_crit["has_critical_blockers"] is True
        assert rq_crit["can_override"] is False
        assert rq_crit["open_questions_count"] == 2
        assert rq_crit["critical_questions_count"] == 1

        fail_override_crit = client.post(
            f"/api/v1/cases/{case.id}/versions",
            json={"override_blockers": True, "override_reason": "Attempting invalid critical override"},
        )
        assert fail_override_crit.status_code == 400
        assert "critical" in fail_override_crit.text.lower()

        # 2. Mark critical question resolved; put minor question into ANSWERED (awaiting review) -> still blocks ordinary!
        q_critical.status = QuestionStatus.RESOLVED
        q_minor.status = QuestionStatus.ANSWERED
        session.add(
            QuestionResponse(
                id=uuid.uuid4(),
                question_id=q_minor.id,
                respondent_id=arjun.id,
                response_text="AI or human draft response awaiting reviewer sign-off.",
                review_state=QuestionResponseReviewState.PENDING_REVIEW,
            )
        )
        session.commit()

        # Departing user (Arjun) must be blocked (403) from approving
        client.post("/api/v1/auth/login", json={"email": "arjun.patel@example.test", "password": "handoffscope-dev-2026"})
        arjun_approve = client.post(f"/api/v1/cases/{case.id}/versions", json={})
        assert arjun_approve.status_code == 403

        # Reviewer (Kabir) gets blocked on ordinary approval and CANNOT override (403)
        client.post("/api/v1/auth/login", json={"email": "kabir.singh@example.test", "password": "handoffscope-dev-2026"})
        me_kabir = client.get("/api/v1/auth/me").json()
        assert "case.approve" in me_kabir["capabilities"]
        assert "case.approve_override" not in me_kabir["capabilities"]

        kabir_rq = client.get(f"/api/v1/cases/{case.id}/review-queue").json()
        assert kabir_rq["can_approve"] is False
        assert kabir_rq["has_critical_blockers"] is False
        assert kabir_rq["can_override"] is False  # Reviewer has no override capability
        assert kabir_rq["awaiting_question_review_count"] == 1

        kabir_ord = client.post(f"/api/v1/cases/{case.id}/versions", json={})
        assert kabir_ord.status_code == 400
        kabir_ovr = client.post(
            f"/api/v1/cases/{case.id}/versions",
            json={"override_blockers": True, "override_reason": "Reviewer trying to override blocker"},
        )
        assert kabir_ovr.status_code == 403

        # Case blocked flag with critical reason blocks even Maya; non-critical doc block is overridable only with >= 10 char reason
        client.post("/api/v1/auth/login", json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"})
        case.is_blocked = True
        case.blocked_reason = "Pending security credential audit"
        session.commit()
        maya_blocked_crit = client.post(
            f"/api/v1/cases/{case.id}/versions",
            json={"override_blockers": True, "override_reason": "Trying to bypass security block"},
        )
        assert maya_blocked_crit.status_code == 400

        case.is_blocked = False
        case.blocked_reason = None
        session.commit()

        # Short override reason rejected
        maya_short = client.post(
            f"/api/v1/cases/{case.id}/versions",
            json={"override_blockers": True, "override_reason": "short"},
        )
        assert maya_short.status_code == 400

        # Valid Lead override succeeds atomically, leaves question unresolved, and preserves metadata in snapshot
        maya_ovr = client.post(
            f"/api/v1/cases/{case.id}/versions",
            json={
                "amendment_reason": "Approved with deferred minor documentation cleanup",
                "override_blockers": True,
                "override_reason": "Slack channel names will be added during onboarding week one.",
            },
        )
        assert maya_ovr.status_code == 201, maya_ovr.text
        v_data = maya_ovr.json()
        snap = v_data["snapshot_json"]
        assert snap["override_metadata"]["overridden"] is True
        assert "Slack channel names" in snap["override_metadata"]["override_reason"]
        assert len(snap["override_metadata"]["overridden_blockers"]) == 1

        session.refresh(q_minor)
        assert q_minor.status == QuestionStatus.ANSWERED  # Never marked resolved by override!

        audit = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "case.approved_with_override", AuditEvent.entity_id == uuid.UUID(v_data["id"]))
            .first()
        )
        assert audit is not None
    finally:
        session.close()
