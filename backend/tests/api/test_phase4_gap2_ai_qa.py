"""Phase 4 (Gap 2) tests: AI Q&A grounding, pending review enforcement, restricted filtering, conflicts, and fallback."""

from __future__ import annotations

import json
import uuid
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func

from app.main import app
from app.core.config import settings
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    ConnectionStatus,
    EvidenceState,
    Priority,
    QuestionStatus,
    ReviewState,
    Sensitivity,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
    TransitionType,
)
from app.db.session import SessionLocal
from app.integrations.llm.gemini_provider import GeminiProvider
from app.modules.audit.models import AuditEvent
from app.modules.handover_cases.models import CaseParticipant, CaseSource, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.questions.models import Question
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


client = TestClient(app)


def test_ai_qa_grounding_restricted_exclusion_fabrication_rejection_and_conflict(monkeypatch):
    session = SessionLocal()
    try:
        maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        aisha = session.query(User).filter(User.email == "aisha.khan@example.test").first()
        arjun = session.query(User).filter(User.email == "arjun.patel@example.test").first()
        assert maya and aisha and arjun

        proj = session.query(Project).filter(Project.slug == "atlas-platform").first()
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == proj.id).scalar() or 0
        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=max_num + 1,
            title=f"Gap 2 AI Q&A Case #{max_num + 1}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.UNDER_REVIEW,
            created_by_id=maya.id,
        )
        session.add(case)
        session.flush()
        session.add_all([
            CaseParticipant(case_id=case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT),
            CaseParticipant(case_id=case.id, user_id=arjun.id, role=CaseParticipantRole.DEPARTING),
        ])

        src = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.GITHUB_REPO,
            name=f"qa-test-src-{uuid.uuid4().hex[:6]}",
            external_id=f"qa-test/{uuid.uuid4().hex[:6]}",
            connection_status=ConnectionStatus.ACTIVE,
            connected_by_id=maya.id,
        )
        session.add(src)
        session.flush()
        session.add(CaseSource(case_id=case.id, connected_source_id=src.id))

        # Unrelated cross-case/other-source record (must NEVER be cited by case)
        other_src = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            name=f"other-src-{uuid.uuid4().hex[:6]}",
            external_id=f"other/{uuid.uuid4().hex[:6]}",
            connection_status=ConnectionStatus.ACTIVE,
        )
        session.add(other_src)
        session.flush()
        cross_case_rec = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=other_src.id,
            source_type="GITHUB_REPO",
            record_type=SourceRecordType.PR,
            external_id="999",
            title="Secret Cross-Source Token Setup",
            body="Do not cite across CaseSource boundary.",
            sensitivity=Sensitivity.GENERAL,
        )

        rec_auth = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src.id,
            source_type="GITHUB_REPO",
            record_type=SourceRecordType.PR,
            external_id="101",
            title="Configure Redis Session Cache Middleware",
            body="Session cache uses Redis Sentinel with 3000ms failover timeout for token validation.",
            state="merged",
            sensitivity=Sensitivity.GENERAL,
        )
        rec_restricted = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src.id,
            source_type="DOCUMENT_UPLOAD",
            record_type=SourceRecordType.DOCUMENT_SECTION,
            external_id="vault-doc-1",
            title="Top Secret Vault Root Key",
            body="SUPER_SECRET_VAULT_KEY_99999 stored in KMS root alias.",
            sensitivity=Sensitivity.RESTRICTED,
        )
        session.add_all([cross_case_rec, rec_auth, rec_restricted])

        pack = TransferPack(id=uuid.uuid4(), case_id=case.id, name="Auth & Caching", status=TransferPackStatus.DRAFT)
        session.add(pack)
        session.flush()

        conflict_claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.DECISION,
            title="Microservices vs Monolith Architecture Conflict",
            body_text="PR #3 adopted microservices while Issue #5 advocates keeping monolith-first payment boundary.",
            evidence_state=EvidenceState.CONFLICTING,
            review_state=ReviewState.PENDING_REVIEW,
        )
        session.add(conflict_claim)

        q_normal = Question(
            id=uuid.uuid4(),
            case_id=case.id,
            transfer_pack_id=pack.id,
            question_text="How is the Redis session cache configured for failover?",
            priority=Priority.HIGH,
            status=QuestionStatus.OPEN,
            created_by_id=aisha.id,
        )
        q_restricted = Question(
            id=uuid.uuid4(),
            case_id=case.id,
            transfer_pack_id=pack.id,
            question_text="What is the SUPER_SECRET_VAULT_KEY_99999 KMS root key value?",
            priority=Priority.CRITICAL,
            status=QuestionStatus.OPEN,
            created_by_id=aisha.id,
        )
        q_conflict = Question(
            id=uuid.uuid4(),
            case_id=case.id,
            transfer_pack_id=pack.id,
            question_text="Should payment service use microservice or monolith architecture?",
            priority=Priority.HIGH,
            status=QuestionStatus.OPEN,
            created_by_id=aisha.id,
        )
        session.add_all([q_normal, q_restricted, q_conflict])
        session.commit()

        # Login as Aisha (Recipient — restricted evidence excluded!)
        client.post("/api/v1/auth/login", json={"email": "aisha.khan@example.test", "password": "handoffscope-dev-2026"})

        # 1. Grounded AI answer for permitted question -> PENDING_REVIEW & never auto-resolved
        res_norm = client.post(f"/api/v1/questions/{q_normal.id}/generate-answer")
        assert res_norm.status_code == 200, res_norm.text
        q_out = res_norm.json()
        assert q_out["status"] == "ANSWERED"  # Not RESOLVED
        ai_resp = q_out["responses"][-1]
        assert ai_resp["is_ai_generated"] is True
        assert ai_resp["respondent_id"] is None
        assert ai_resp["review_state"] == "PENDING_REVIEW"
        assert ai_resp["answer_status"] == "answered"
        assert any(r["source_id"] == str(rec_auth.id) for r in ai_resp["evidence_references"])

        # Source citation drilldown works for permitted record, returns 403 for RESTRICTED
        ok_src = client.get(f"/api/v1/cases/{case.id}/sources/records/{rec_auth.id}")
        assert ok_src.status_code == 200
        assert "3000ms" in ok_src.json()["body"]

        blocked_src = client.get(f"/api/v1/cases/{case.id}/sources/records/{rec_restricted.id}")
        assert blocked_src.status_code == 403

        # 2. Restricted record must be excluded BEFORE prompt reaches LLM -> insufficient & zero secret leakage
        captured_prompts: list[str] = []
        from app.integrations.llm.mock_provider import MockLLMProvider

        orig_answer = MockLLMProvider.answer_question

        def spy_answer(self, system_prompt, user_prompt, response_schema, **kwargs):
            captured_prompts.append(user_prompt)
            return orig_answer(self, system_prompt, user_prompt, response_schema, **kwargs)

        monkeypatch.setattr(MockLLMProvider, "answer_question", spy_answer)
        res_rest = client.post(f"/api/v1/questions/{q_restricted.id}/generate-answer")
        assert res_rest.status_code == 200
        assert captured_prompts and "SUPER_SECRET_VAULT_KEY_99999" not in captured_prompts[-1].split("PERMITTED EVIDENCE SOURCES")[1]
        assert res_rest.json()["responses"][-1]["answer_status"] == "insufficient"

        # 3. Conflicting question cites conflict claim and detects conflicting status
        res_conf = client.post(f"/api/v1/questions/{q_conflict.id}/generate-answer")
        assert res_conf.status_code == 200
        assert res_conf.json()["responses"][-1]["answer_status"] == "conflicting"

        # 4. Human response preserved cleanly alongside AI draft (Arjun adds human answer)
        client.post("/api/v1/auth/login", json={"email": "arjun.patel@example.test", "password": "handoffscope-dev-2026"})
        human_res = client.post(
            f"/api/v1/questions/{q_normal.id}/responses",
            json={"response_text": "Human note: sentinel timeout was tuned last Friday."},
        )
        assert human_res.status_code == 200
        resps = human_res.json()["responses"]
        assert len(resps) == 2
        assert resps[0]["is_ai_generated"] is True
        assert resps[1]["is_ai_generated"] is False
        assert resps[1]["respondent_id"] == str(arjun.id)

        # 5. Live LLM returning fabricated/cross-case ID MUST be stripped & downgraded to insufficient
        monkeypatch.setattr(settings, "LLM_API_KEY", "dummy-live-key")

        def fake_gemini_fabricated(url, headers=None, json=None, timeout=None):
            fake_payload = {
                "answer_text": "Claiming cross-case record.",
                "answer_status": "answered",
                "evidence_references": [
                    {"source_id": str(uuid.uuid4()), "source_type": "SOURCE_RECORD", "relevance": "fabricated"},
                    {"source_id": str(cross_case_rec.id), "source_type": "SOURCE_RECORD", "relevance": "cross-source"},
                ],
            }
            import json as _json
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": _json.dumps(fake_payload)}]}}]})

        monkeypatch.setattr(httpx, "post", fake_gemini_fabricated)
        res_fab = client.post(f"/api/v1/questions/{q_restricted.id}/generate-answer")
        assert res_fab.status_code == 200
        fab_resp = res_fab.json()["responses"][-1]
        assert fab_resp["evidence_references"] == []
        assert fab_resp["answer_status"] == "insufficient"

        # 6. Provider failure activates explicit mock_fallback (non-silent!) + audit event
        def fake_gemini_down(url, headers=None, json=None, timeout=None):
            return httpx.Response(503, text="Service Unavailable")

        monkeypatch.setattr(httpx, "post", fake_gemini_down)
        monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 0)
        res_fb = client.post(f"/api/v1/questions/{q_normal.id}/generate-answer")
        assert res_fb.status_code == 200
        fb_resp = res_fb.json()["responses"][-1]
        assert fb_resp["ai_provider"] == "mock_fallback"
        assert fb_resp["provenance"]["fallback_used"] is True

        audit_q = session.query(AuditEvent).filter(
            AuditEvent.action == "question.ai_answer_generated",
            AuditEvent.entity_id == q_normal.id,
        ).first()
        assert audit_q is not None
    finally:
        session.close()
