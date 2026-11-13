"""Tests for Phase R3-2: Snapshot-pinned, clearance-first Conversational RAG Assistant."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

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
from app.integrations.llm.mock_provider import MockLLMProvider
from app.integrations.llm.schemas.qa import QuestionAnswerResult
from app.main import app
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.projects.models import Project
from app.modules.rag.indexing import index_approved_version_chunks
from app.modules.rag.models import KnowledgeChunk
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.service import build_canonical_snapshot_dict
from app.modules.sharing.models import ShareGrant
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


def _login_as(client: TestClient, email: str) -> None:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "handoffscope-dev-2026"},
    )
    assert res.status_code == 200, res.text
    csrf_token = res.cookies.get("csrf_token") or res.json().get("csrf_token", "")
    client.headers.update({"X-CSRF-Token": csrf_token})


def _seed_rag_case() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    secret_phrase = f"VAULT-SECRET-{uuid.uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        proj = db.query(Project).first()
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        kabir = db.query(User).filter(User.email == "kabir.singh@example.test").first()
        aisha = db.query(User).filter(User.email == "aisha.khan@example.test").first()

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=921,
            title="R3 RAG Test Case",
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
            name="Auth Service Architecture",
            component_area="auth",
            sort_order=1,
        )
        db.add(pack)
        db.flush()

        c_public = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.DECISION,
            title="Token Timeout Policy",
            body_text="Transaction retry timeout was configured to 5000ms after Redis removal.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.HIGH,
        )
        c_restricted = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.RISK,
            title="HSM Vault Master Password",
            body_text=f"Production master credential is {secret_phrase} stored in vault.",
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
                locator="vault-keys.md#L12",
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

        # Live mutation after v1 + freeze v2
        c_public.body_text = "Timeout bumped to 9999ms in live v2 amendment."
        db.flush()
        snap_v2, _, _ = build_canonical_snapshot_dict(
            db,
            case=case,
            version_number=2,
            approved_at=now,
            approved_by_id=kabir.id,
            approved_by_name=kabir.display_name,
            amendment_reason="Changed timeout to 9999ms",
        )
        v2 = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=2,
            approved_by_id=kabir.id,
            approved_at=now,
            snapshot_json=snap_v2,
            is_current=True,
            amendment_reason="Changed timeout to 9999ms",
            previous_version_id=v1.id,
        )
        db.add(v2)
        db.flush()
        db.add(ShareGrant(handover_version_id=v1.id, recipient_user_id=aisha.id, granted_by=maya.id))
        db.add(ShareGrant(handover_version_id=v2.id, recipient_user_id=aisha.id, granted_by=maya.id))
        db.commit()
        return case.id, v1.id, v2.id, secret_phrase
    finally:
        db.close()


def test_rag_clearance_first_snapshot_isolation_and_citation_validation():
    case_id, v1_id, v2_id, secret_phrase = _seed_rag_case()
    client = TestClient(app)

    # 1. Idempotent indexing on v1 creates exact chunks once
    db = SessionLocal()
    try:
        cnt1, mode1, _, _ = index_approved_version_chunks(db, case_id=case_id, version_id=v1_id)
        db.commit()
        cnt2, _, _, _ = index_approved_version_chunks(db, case_id=case_id, version_id=v1_id)
        db.commit()
        assert cnt1 == cnt2 and cnt1 >= 2
        assert mode1 == "lexical_only"
        assert db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id == v1_id).count() == cnt1
    finally:
        db.close()

    # 2. Recipient cannot request DRAFT_CONTEXT
    _login_as(client, "aisha.khan@example.test")
    assert (
        client.post(
            f"/api/v1/cases/{case_id}/chat/ask",
            json={"question": "What timeout was configured?", "context_mode": "DRAFT_CONTEXT"},
        ).status_code
        == 403
    )

    # 3. Recipient querying v1 gets 5000ms with real citation, isolated from v2 (9999ms)
    captured_prompts: list[str] = []
    real_answer_fn = MockLLMProvider.answer_question

    def spy_answer_question(self, system_prompt, user_prompt, response_schema, **kwargs):
        captured_prompts.append(user_prompt)
        return real_answer_fn(self, system_prompt, user_prompt, response_schema, **kwargs)

    with patch.object(MockLLMProvider, "answer_question", spy_answer_question), patch(
        "app.modules.rag.service.get_llm_provider", return_value=MockLLMProvider()
    ):
        r_v1 = client.post(
            f"/api/v1/cases/{case_id}/chat/ask",
            json={"question": "Why was the transaction timeout set to 5000ms?", "version_id": str(v1_id)},
        )
        assert r_v1.status_code == 200, r_v1.text
        d_v1 = r_v1.json()
        assert d_v1["thread"]["pinned_version_number"] == 1
        assert "5000ms" in d_v1["assistant_message"]["content_text"]
        assert "9999ms" not in d_v1["assistant_message"]["content_text"]
        assert d_v1["assistant_message"]["grounding_status"] == "ANSWERED"
        assert len(d_v1["assistant_message"]["citations"]) >= 1
        assert d_v1["assistant_message"]["retrieval_mode"] == "lexical_only"
        thread_id = d_v1["thread"]["id"]

        # 4. Pinned v1 thread rejects attempts to switch silently to v2
        r_drift = client.post(
            f"/api/v1/cases/{case_id}/chat/ask",
            json={"question": "Followup", "thread_id": thread_id, "version_id": str(v2_id)},
        )
        assert r_drift.status_code == 400

        # 5. Restricted query as Recipient must exclude restricted chunk BEFORE prompt construction
        captured_prompts.clear()
        r_sec = client.post(
            f"/api/v1/cases/{case_id}/chat/ask",
            json={"question": "What is the HSM Vault Master Password credential?", "version_id": str(v1_id)},
        )
        assert r_sec.status_code == 200
        d_sec = r_sec.json()
        assert d_sec["restricted_evidence_excluded"] is True
        assert secret_phrase not in d_sec["assistant_message"]["content_text"]
        assert not any(secret_phrase in p for p in captured_prompts), "Restricted secret reached LLM prompt!"

    # 6. Lead (Maya) DOES have clearance to query restricted content
    _login_as(client, "maya.sharma@example.test")
    with patch("app.modules.rag.service.get_llm_provider", return_value=MockLLMProvider()):
        r_lead = client.post(
            f"/api/v1/cases/{case_id}/chat/ask",
            json={"question": "What is the HSM Vault Master Password credential?", "version_id": str(v1_id)},
        )
        assert r_lead.status_code == 200
        assert secret_phrase in r_lead.json()["assistant_message"]["content_text"]

    # 7. Fabricated citation UUID returned by LLM is rejected cleanly (never passed through)
    class FakeHallucinatingProvider(MockLLMProvider):
        def answer_question(self, system_prompt, user_prompt, response_schema, **kwargs):
            res = QuestionAnswerResult.model_validate({
                "answer_text": "Invented answer citing non-existent UUID.",
                "answer_status": "answered",
                "evidence_references": [
                    {
                        "source_id": str(uuid.uuid4()),
                        "source_type": "CLAIM",
                        "title": "Fake Source",
                        "excerpt": "Hallucinated excerpt",
                        "locator": "fake.py#L1",
                    }
                ],
                "limitations": None,
                "conflicts": [],
            })
            return res, {"provider_mode": "mock", "model_used": "fake-hallucinator"}

    with patch("app.modules.rag.service.get_llm_provider", return_value=FakeHallucinatingProvider()):
        r_fake = client.post(
            f"/api/v1/cases/{case_id}/chat/ask",
            json={"question": "What timeout was set in 5000ms?", "version_id": str(v1_id)},
        )
        assert r_fake.status_code == 200
        d_fake = r_fake.json()
        assert d_fake["assistant_message"]["citations"] == []
        assert d_fake["assistant_message"]["grounding_status"] == "INSUFFICIENT_EVIDENCE"
