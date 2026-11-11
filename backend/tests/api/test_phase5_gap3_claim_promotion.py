"""Phase 5 (Gap 3) tests: linked claim clarification revision & standalone automatic Operational Note promotion."""

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
    ProjectRole,
    QuestionResponseReviewState,
    QuestionStatus,
    ReviewState,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
    TransitionType,
)
from app.db.session import SessionLocal
from app.modules.audit.models import AuditEvent
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project, ProjectMembership
from app.modules.questions.models import Question, QuestionResponse
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


client = TestClient(app)


def test_claim_promotion_linked_revision_idempotency_and_edge_cases():
    session = SessionLocal()
    try:
        maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        kabir = session.query(User).filter(User.email == "kabir.singh@example.test").first()
        aisha = session.query(User).filter(User.email == "aisha.khan@example.test").first()
        arjun = session.query(User).filter(User.email == "arjun.patel@example.test").first()
        assert maya and kabir and aisha and arjun

        seed_proj = session.query(Project).filter(Project.slug == "atlas-platform").first()
        assert seed_proj is not None
        proj = Project(
            id=uuid.uuid4(),
            workspace_id=seed_proj.workspace_id,
            name="Gap 3 Isolated Project",
            slug=f"gap3-isolated-{uuid.uuid4().hex[:8]}",
            description="Hermetic project for Gap 3 RBAC and promotion tests.",
        )
        session.add(proj)
        session.flush()
        session.add_all([
            ProjectMembership(project_id=proj.id, user_id=maya.id, role=ProjectRole.LEAD),
            ProjectMembership(project_id=proj.id, user_id=kabir.id, role=ProjectRole.REVIEWER),
            ProjectMembership(project_id=proj.id, user_id=aisha.id, role=ProjectRole.CONTRIBUTOR),
            ProjectMembership(project_id=proj.id, user_id=arjun.id, role=ProjectRole.CONTRIBUTOR),
        ])
        max_num = 0
        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=max_num + 1,
            title=f"Gap 3 Promotion Case #{max_num + 1}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.UNDER_REVIEW,
            created_by_id=maya.id,
        )
        session.add(case)
        session.flush()
        session.add_all([
            CaseParticipant(case_id=case.id, user_id=kabir.id, role=CaseParticipantRole.REVIEWER),
            CaseParticipant(case_id=case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT),
            CaseParticipant(case_id=case.id, user_id=arjun.id, role=CaseParticipantRole.DEPARTING),
        ])

        # Cross-cutting pack sorted BEFORE? Make sure primary domain pack is resolved instead of arbitrary cross-cutting
        cross_pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Cross-Cutting Risks & Operational Gaps",
            component_area="Cross-Cutting",
            sort_order=0,
            status=TransferPackStatus.DRAFT,
        )
        domain_pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Auth Service Primary Pack",
            component_area="Authentication",
            sort_order=1,
            is_primary=True,
            status=TransferPackStatus.DRAFT,
        )
        session.add_all([cross_pack, domain_pack])
        session.flush()

        linked_claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=domain_pack.id,
            claim_type=ClaimType.WORK_ITEM,
            title="Multi-Tenant Rate Limiter Config",
            body_text="Original statement pending subnet clarification.",
            evidence_state=EvidenceState.UNKNOWN,
            review_state=ReviewState.NEEDS_CLARIFICATION,
        )
        session.add(linked_claim)
        session.flush()

        q_linked = Question(
            id=uuid.uuid4(),
            case_id=case.id,
            transfer_pack_id=domain_pack.id,
            claim_id=linked_claim.id,
            question_text="What is the per-tenant Redis rate limit threshold?",
            priority=Priority.HIGH,
            status=QuestionStatus.ANSWERED,
            created_by_id=kabir.id,
        )
        session.add(q_linked)
        session.flush()
        session.add(
            QuestionResponse(
                id=uuid.uuid4(),
                question_id=q_linked.id,
                respondent_id=arjun.id,
                response_text="100 requests per minute per tenant using token bucket in Redis db 2.",
                review_state=QuestionResponseReviewState.PENDING_REVIEW,
            )
        )

        q_standalone = Question(
            id=uuid.uuid4(),
            case_id=case.id,
            question_text="Which cron job clears expired session keys nightly?",
            why_it_matters="Prevents Redis OOM alerts.",
            priority=Priority.MEDIUM,
            status=QuestionStatus.ANSWERED,
            created_by_id=aisha.id,
        )
        session.add(q_standalone)
        session.flush()
        session.add(
            QuestionResponse(
                id=uuid.uuid4(),
                question_id=q_standalone.id,
                respondent_id=arjun.id,
                response_text="Nightly k8s CronJob `session-gc` runs at 03:00 UTC.",
                review_state=QuestionResponseReviewState.PENDING_REVIEW,
            )
        )

        # Case with NO packs at all
        no_pack_case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=max_num + 2,
            title=f"No Pack Case #{max_num + 2}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.DRAFT,
            created_by_id=maya.id,
        )
        session.add(no_pack_case)
        session.flush()
        q_nopack = Question(
            id=uuid.uuid4(),
            case_id=no_pack_case.id,
            question_text="Any runbook location?",
            status=QuestionStatus.ANSWERED,
            created_by_id=maya.id,
        )
        session.add(q_nopack)
        session.flush()
        session.add(
            QuestionResponse(
                id=uuid.uuid4(),
                question_id=q_nopack.id,
                respondent_id=arjun.id,
                response_text="Stored in docs/runbook.md.",
                review_state=QuestionResponseReviewState.PENDING_REVIEW,
            )
        )
        session.commit()

        # 0. Unauthorized user (Aisha) rejected with 403 when trying to accept an answer
        client.post("/api/v1/auth/login", json={"email": "aisha.khan@example.test", "password": "handoffscope-dev-2026"})
        unauth = client.patch(f"/api/v1/questions/{q_standalone.id}/review", json={"action": "accept"})
        assert unauth.status_code == 403

        # Login as Reviewer (Kabir)
        client.post("/api/v1/auth/login", json={"email": "kabir.singh@example.test", "password": "handoffscope-dev-2026"})

        # 1. Accept linked question -> preserves original text, appends traceable block, clears NEEDS_CLARIFICATION -> PENDING_REVIEW
        # Pure human confirmation without repo evidence must NOT become repository-SUPPORTED (must be INFERRED!)
        linked_res = client.patch(f"/api/v1/questions/{q_linked.id}/review", json={"action": "accept"})
        assert linked_res.status_code == 200, linked_res.text
        assert linked_res.json()["promotion_result"]["status"] == "linked_claim_updated"

        session.expire_all()
        updated_linked = session.query(Claim).filter(Claim.id == linked_claim.id).first()
        assert updated_linked.original_body_text == "Original statement pending subnet clarification."
        assert "100 requests per minute per tenant" in updated_linked.body_text
        assert updated_linked.review_state == ReviewState.PENDING_REVIEW
        assert updated_linked.evidence_state == EvidenceState.INFERRED
        assert updated_linked.provenance_json["human_confirmed"] is True

        # 2. Accept standalone question -> promotes ONCE into domain_pack (NOT cross_pack!) as OPERATIONAL_NOTE
        stand_res = client.patch(
            f"/api/v1/questions/{q_standalone.id}/review",
            json={
                "action": "amend",
                "amended_text": "Nightly Kubernetes CronJob `session-gc` runs at 03:00 UTC in prod.",
                "notes": "Clarified exact namespace/cron.",
            },
        )
        assert stand_res.status_code == 200, stand_res.text
        promo = stand_res.json()["promotion_result"]
        assert promo["status"] == "promoted_operational_note"
        assert promo["pack_id"] == str(domain_pack.id)

        promoted_claims = session.query(Claim).filter(Claim.origin_question_id == q_standalone.id).all()
        assert len(promoted_claims) == 1
        p_claim = promoted_claims[0]
        assert p_claim.claim_type == ClaimType.OPERATIONAL_NOTE
        assert "03:00 UTC" in p_claim.body_text
        assert p_claim.evidence_state == EvidenceState.INFERRED  # Honest: pure human answer, no repo citation

        # 3. Reopen and re-accept standalone question -> MUST remain idempotent (still exactly 1 claim!)
        client.patch(f"/api/v1/questions/{q_standalone.id}", json={"status": "OPEN"})
        client.patch(f"/api/v1/questions/{q_standalone.id}/review", json={"action": "accept"})
        assert session.query(Claim).filter(Claim.origin_question_id == q_standalone.id).count() == 1

        # 4. No primary pack case -> cleanly skipped without silent pack creation
        client.post("/api/v1/auth/login", json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"})
        nopack_res = client.patch(f"/api/v1/questions/{q_nopack.id}/review", json={"action": "accept"})
        assert nopack_res.status_code == 200
        assert nopack_res.json()["promotion_result"]["status"] == "skipped_no_primary_pack"
        assert session.query(TransferPack).filter(TransferPack.case_id == no_pack_case.id).count() == 0

        # 5. Cross-case linked claim atomic rollback
        foreign_claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=domain_pack.id,
            claim_type=ClaimType.WORK_ITEM,
            title="Foreign claim",
            body_text="Belongs to Case 1, not no_pack_case.",
        )
        session.add(foreign_claim)
        session.flush()
        q_cross = Question(
            id=uuid.uuid4(),
            case_id=no_pack_case.id,
            claim_id=foreign_claim.id,
            question_text="Trying cross-case link",
            status=QuestionStatus.ANSWERED,
            created_by_id=maya.id,
        )
        session.add(q_cross)
        session.flush()
        session.add(
            QuestionResponse(
                id=uuid.uuid4(),
                question_id=q_cross.id,
                respondent_id=arjun.id,
                response_text="Should roll back cleanly.",
                review_state=QuestionResponseReviewState.PENDING_REVIEW,
            )
        )
        session.commit()

        cross_res = client.patch(f"/api/v1/questions/{q_cross.id}/review", json={"action": "accept"})
        assert cross_res.status_code == 400
        session.expire_all()
        assert session.query(Question).filter(Question.id == q_cross.id).first().status == QuestionStatus.ANSWERED
    finally:
        session.close()
