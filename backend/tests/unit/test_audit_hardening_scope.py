"""Unit and regression tests verifying audit hardening requirements across:
- Claims review state machine invariants
- Evidence clearance masking and hallucinated citation discarding
- Secret redaction ReDoS resistance and immutability
- Questions lifecycle, answer validation, and AI drafting error resilience
- Transaction rollbacks
"""

import uuid
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.db.base import SessionLocal
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    EvidenceState,
    EvidenceType,
    Freshness,
    Priority,
    ProjectRole,
    QuestionResponseReviewState,
    QuestionStatus,
    ReviewState,
    Sensitivity,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
    TransitionType,
)
from app.modules.claims.models import Claim as ExportedClaim
from app.modules.evidence.clearance import (
    RESTRICTED_EVIDENCE_PLACEHOLDER,
    has_restricted_clearance,
)
from app.modules.evidence.models import ClaimEvidence
from app.modules.evidence.service import review_claim
from app.modules.handover_cases.models import CaseParticipant, CaseSource, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project, ProjectMembership
from app.modules.questions.models import Question, QuestionResponse
from app.modules.questions.schemas import QuestionUpdate
from app.modules.questions.service import (
    add_response,
    generate_ai_answer,
    review_response,
    update_question,
)
from app.modules.reconstruction.service import run_extraction
from app.modules.sharing.redactor import redact_secrets_inline
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


client = TestClient(app)


def test_claims_reexport_facade():
    """Verify that backend/app/modules/claims/ provides canonical exports."""
    from app.modules.claims import Claim as C1, router as r1, review_claim as rc1
    from app.modules.claims.schemas import ClaimDetailOut, ClaimOut, ClaimUpdate, ReviewClaimRequest
    assert C1 is Claim
    assert callable(rc1)
    assert r1 is not None
    assert ClaimDetailOut is not None


def test_claim_review_state_machine_invariants():
    """Verify claim review state transitions and invalid jump rejections (HTTP 400)."""
    db = SessionLocal()
    try:
        user = db.query(User).first()
        pack = db.query(TransferPack).first()
        assert user and pack

        claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.DECISION,
            title="State Machine Invariant Claim",
            body_text="Test invariant enforcement.",
            evidence_state=EvidenceState.SUPPORTED,
            freshness=Freshness.CURRENT,
            review_state=ReviewState.PENDING_REVIEW,
        )
        db.add(claim)
        db.commit()

        # 1. PENDING_REVIEW cannot be resubmitted/reopened directly
        with pytest.raises(ValueError, match="already in PENDING_REVIEW"):
            review_claim(db, claim_id=claim.id, user_id=user.id, action="resubmit")

        # 2. Reject transition from PENDING_REVIEW
        c_rej = review_claim(db, claim_id=claim.id, user_id=user.id, action="reject", reason="Rejected for budget")
        assert c_rej.review_state == ReviewState.REJECTED

        # 3. From REJECTED, cannot jump directly to ACCEPTED (must raise ValueError -> 400)
        with pytest.raises(ValueError, match="Cannot accept claim in state 'REJECTED'"):
            review_claim(db, claim_id=claim.id, user_id=user.id, action="accept")

        # 4. From REJECTED, can resubmit -> PENDING_REVIEW
        c_resub = review_claim(db, claim_id=claim.id, user_id=user.id, action="resubmit")
        assert c_resub.review_state == ReviewState.PENDING_REVIEW

        # 5. Flag for clarification
        c_clar = review_claim(db, claim_id=claim.id, user_id=user.id, action="needs_clarification", reason="Need docs")
        assert c_clar.review_state == ReviewState.NEEDS_CLARIFICATION

        # 6. From NEEDS_CLARIFICATION, cannot flag needs_clarification again
        with pytest.raises(ValueError, match="Only PENDING_REVIEW claims can be flagged for clarification"):
            review_claim(db, claim_id=claim.id, user_id=user.id, action="needs_clarification", reason="More docs")

        # 7. From NEEDS_CLARIFICATION, can accept
        c_acc = review_claim(db, claim_id=claim.id, user_id=user.id, action="accept")
        assert c_acc.review_state == ReviewState.ACCEPTED

        # 8. From ACCEPTED, cannot directly reject without reopening
        with pytest.raises(ValueError, match="Cannot reject claim in state 'ACCEPTED'"):
            review_claim(db, claim_id=claim.id, user_id=user.id, action="reject", reason="Now reject")
    finally:
        db.close()


def test_clearance_masking_on_claim_endpoints():
    """Verify restricted claims are masked with RESTRICTED_EVIDENCE_PLACEHOLDER for unprivileged viewers."""
    db = SessionLocal()
    try:
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        aisha = db.query(User).filter(User.email == "aisha.khan@example.test").first()
        proj = db.query(Project).first()
        assert maya and aisha and proj

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=8888,
            title="Clearance Masking Test Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.UNDER_REVIEW,
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()
        db.add(CaseParticipant(case_id=case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT))
        pack = TransferPack(id=uuid.uuid4(), case_id=case.id, name="Security Pack", component_area="Security")
        db.add(pack)
        db.flush()

        # Seed restricted claim
        claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.RISK,
            title="Confidential HSM Key Custody",
            body_text="Confidential production HSM master key material.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.PENDING_REVIEW,
        )
        db.add(claim)
        db.flush()

        db.add(
            ClaimEvidence(
                id=uuid.uuid4(),
                claim_id=claim.id,
                excerpt="Sensitive key config details",
                locator="VaultDoc:sec.md",
                evidence_type=EvidenceType.DIRECT_REFERENCE,
                is_restricted=True,
            )
        )
        db.commit()

        # 1. Anonymous / unprivileged GET /claims/{id} masks restricted body
        res = client.get(f"/api/v1/claims/{claim.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["body_text"] == RESTRICTED_EVIDENCE_PLACEHOLDER
        assert data["evidence"][0]["excerpt"] == "[WITHHELD BY ACCESS POLICY]"
        assert data["evidence"][0]["locator"] == "Restricted Document Reference"

        # 2. Case claims list masks restricted body
        list_res = client.get(f"/api/v1/cases/{case.id}/claims")
        assert list_res.status_code == 200
        claims_list = list_res.json()
        target = next(c for c in claims_list if c["id"] == str(claim.id))
        assert target["body_text"] == RESTRICTED_EVIDENCE_PLACEHOLDER
    finally:
        db.close()


def test_reconstruction_hallucinated_citation_discarding():
    """Verify that citations with non-existent source records are completely discarded before saving."""
    from app.integrations.llm.schemas.extraction import (
        CandidateTransferPack,
        EvidenceReference,
        ExtractedWorkItem,
        ExtractionResult,
    )
    from app.integrations.llm.mock_provider import MockLLMProvider
    from app.modules.reconstruction import service as recon_service

    db = SessionLocal()
    try:
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        proj = db.query(Project).first()
        assert maya and proj

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=8889,
            title="Hallucination Discarding Test Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.INGESTING,
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()

        src = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="test-hallucination-src",
            external_id="test/hallucination",
            connection_status="ACTIVE",
            connected_by_id=maya.id,
        )
        db.add(src)
        db.flush()
        db.add(CaseSource(case_id=case.id, connected_source_id=src.id))

        real_sr = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src.id,
            source_type="GITHUB_REPO",
            record_type=SourceRecordType.COMMIT,
            external_id="real-c1",
            title="Real commit on db connection pool",
            body="Configured pool size to 25.",
        )
        db.add(real_sr)
        db.commit()

        # Fabricate an LLM extraction output containing 1 valid citation and 2 hallucinated citations
        hallucinated_sr_id = str(uuid.uuid4())
        mock_result = ExtractionResult(
            transfer_packs=[
                CandidateTransferPack(
                    name="Database Architecture",
                    description="DB configuration",
                    component_area="Database",
                    work_items=[
                        ExtractedWorkItem(
                            title="Database connection pooling",
                            description="Tuned pool size to 25 connections",
                            current_state="completed",
                            evidence=[
                                EvidenceReference(
                                    source_record_id=str(real_sr.id),
                                    excerpt="Configured pool size to 25",
                                    locator="commit",
                                ),
                                EvidenceReference(
                                    source_record_id=hallucinated_sr_id,
                                    excerpt="Non-existent hallucinated excerpt",
                                    locator="hallucinated",
                                ),
                                EvidenceReference(
                                    source_record_id="invalid-uuid-string",
                                    excerpt="Bogus text",
                                    locator="bogus",
                                ),
                            ],
                        )
                    ],
                )
            ]
        )

        class CustomMockProvider(MockLLMProvider):
            def extract_structured(self, system_prompt, user_prompt, response_schema, **kwargs):
                return mock_result, {"model_used": "custom-mock", "provider_mode": "mock"}

        import app.modules.reconstruction.service as recon_mod
        orig_get_provider = recon_mod.get_llm_provider
        recon_mod.get_llm_provider = lambda: CustomMockProvider()
        try:
            res = recon_service.run_extraction(db, case_id=case.id, actor_id=maya.id)
            assert res.status == "COMPLETED"

            # Check saved ClaimEvidence rows
            claim = (
                db.query(Claim)
                .filter(Claim.title == "Database connection pooling")
                .first()
            )
            assert claim is not None
            evidence_rows = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim.id).all()
            # Only the 1 real SourceRecord should be saved; the 2 hallucinated ones must be discarded!
            assert len(evidence_rows) == 1
            assert evidence_rows[0].source_record_id == real_sr.id
        finally:
            recon_mod.get_llm_provider = orig_get_provider
    finally:
        db.close()


def test_secret_redactor_no_redos_and_clean_projections():
    """Verify redactor regex does not backtrack catastrophically and preserves stored input."""
    # Long repetitive string that would cause ReDoS with quadratic regex
    malicious_input = "PASSWORD" * 3000 + " = not_a_secret"
    res = redact_secrets_inline(malicious_input)
    assert res is not None

    # Normal config secret redaction
    config_sample = 'DB_PASSWORD = "super_secret_production_password_12345"'
    redacted = redact_secrets_inline(config_sample)
    assert "super_secret_production_password_12345" not in redacted.redacted_text
    assert "[REDACTED:SECRET]" in redacted.redacted_text
    # Original string is unchanged
    assert "super_secret_production_password_12345" in config_sample


def test_questions_lifecycle_and_reopen():
    """Verify answer validation, status transitions, and reopening."""
    db = SessionLocal()
    try:
        user = db.query(User).first()
        case = db.query(HandoverCase).first()
        assert user and case

        q = Question(
            case_id=case.id,
            question_text="Lifecycle test question?",
            why_it_matters="Verification",
            status=QuestionStatus.OPEN,
            created_by_id=user.id,
        )
        db.add(q)
        db.commit()

        # 1. Answering with empty text fails with ValueError
        with pytest.raises(ValueError, match="cannot be empty"):
            add_response(db, question_id=q.id, user_id=user.id, response_text="   ")

        # 2. Dismiss from OPEN
        q_dismissed = update_question(db, question_id=q.id, user_id=user.id, data=QuestionUpdate(status="DISMISSED"))
        assert q_dismissed.status == "DISMISSED"

        # 3. Answering a DISMISSED question fails
        with pytest.raises(ValueError, match="Cannot answer a question in status 'DISMISSED'"):
            add_response(db, question_id=q.id, user_id=user.id, response_text="Answer to dismissed")

        # 4. Reopen via status="REOPENED"
        q_reopened = update_question(db, question_id=q.id, user_id=user.id, data=QuestionUpdate(status="REOPENED"))
        assert q_reopened.status == "OPEN"

        # 5. Answer now succeeds
        q_answered = add_response(db, question_id=q.id, user_id=user.id, response_text="Valid answer text")
        assert q_answered.status == "ANSWERED"
    finally:
        db.close()


def test_ai_draft_error_resilience():
    """Verify that live LLM timeout or JSON errors during AI drafting fall back cleanly without 500 error."""
    db = SessionLocal()
    try:
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        case = db.query(HandoverCase).first()
        assert maya and case

        q = Question(
            case_id=case.id,
            question_text="How to handle Redis failover?",
            why_it_matters="Critical runbook",
            status=QuestionStatus.OPEN,
            created_by_id=maya.id,
        )
        db.add(q)
        db.commit()

        # Simulate provider raising a TimeoutError or json decode error
        class BrokenProvider:
            def answer_question(self, *args, **kwargs):
                raise TimeoutError("Simulated LLM network timeout after 30s")

        import app.modules.questions.service as q_service
        orig_provider_getter = q_service.get_llm_provider
        q_service.get_llm_provider = lambda: BrokenProvider()
        try:
            # Must handle timeout gracefully and succeed rather than crashing
            result = generate_ai_answer(db, question_id=q.id, user_id=maya.id)
            assert result is not None
            assert len(result.responses) >= 1
            latest_resp = result.responses[-1]
            assert latest_resp.is_ai_generated is True
            # Verify fallback was engaged
            assert latest_resp.provenance.get("fallback_used") is True
        finally:
            q_service.get_llm_provider = orig_provider_getter
    finally:
        db.close()
