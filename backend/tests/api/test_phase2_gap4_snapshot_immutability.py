"""Phase 2 (Gap 4) tests: snapshot-first successor projection, immutability, redaction, and integrity checks."""

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
    EvidenceType,
    Priority,
    ReviewState,
    TransferPackStatus,
    TransitionType,
)
from app.db.session import SessionLocal
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.reviews.models import HandoverVersion
from app.modules.reviews.service import create_approved_version
from app.modules.sharing.service import create_share_grant
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


client = TestClient(app)


def test_successor_projection_reads_immutable_snapshot_and_blocks_draft_leakage():
    session = SessionLocal()
    try:
        maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        aisha = session.query(User).filter(User.email == "aisha.khan@example.test").first()
        neha = session.query(User).filter(User.email == "neha.gupta@example.test").first()
        assert maya and aisha and neha

        project_id = maya.workspace_memberships[0].workspace.projects[0].id
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == project_id).scalar() or 0
        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=project_id,
            case_number=max_num + 1,
            title=f"Snapshot Immutability Test #{max_num + 1}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.UNDER_REVIEW,
            created_by_id=maya.id,
        )
        session.add(case)
        session.flush()
        session.add(CaseParticipant(case_id=case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT))

        pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Core Payment Routing",
            component_area="Payments",
            status=TransferPackStatus.READY_FOR_REVIEW,
        )
        session.add(pack)
        session.flush()

        c1 = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.NEXT_ACTION,
            title="Approved Next Action Title",
            body_text="Original approved body text.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.HIGH,
        )
        c_restr = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.OPERATIONAL_NOTE,
            title="KMS Vault Key Procedure",
            body_text="Secret root vault details.",
            evidence_state=EvidenceState.SUPPORTED,
            review_state=ReviewState.ACCEPTED,
            priority=Priority.CRITICAL,
        )
        session.add_all([c1, c_restr])
        session.flush()

        session.add(ClaimEvidence(claim_id=c1.id, excerpt="Approved evidence excerpt", evidence_type=EvidenceType.DIRECT_REFERENCE, is_restricted=False))
        session.add(ClaimEvidence(claim_id=c_restr.id, excerpt="Secret key", locator="DOC:vault.md", evidence_type=EvidenceType.DIRECT_REFERENCE, is_restricted=True))
        session.commit()

        # Approve draft -> must create schema_version 2 + snapshot_hash
        v1 = create_approved_version(session, case_id=case.id, user_id=maya.id)
        assert v1.snapshot_json["schema_version"] == 2
        assert v1.snapshot_json["metadata"].get("snapshot_hash")

        create_share_grant(session, version_id=v1.id, recipient_user_id=aisha.id, granted_by=maya.id)

        # Mutate live DB AFTER v1 approval (simulate post-approval draft edits / new pack)
        c1.title = "MUTATED DRAFT TITLE AFTER APPROVAL"
        c1.body_text = "MUTATED DRAFT BODY SHOULD NOT LEAK"
        extra_pack = TransferPack(id=uuid.uuid4(), case_id=case.id, name="Unapproved Draft Pack", status=TransferPackStatus.DRAFT)
        session.add(extra_pack)
        session.commit()

        # Login as Aisha (Recipient) and inspect continuation view
        login_res = client.post("/api/v1/auth/login", json={"email": "aisha.khan@example.test", "password": "handoffscope-dev-2026"})
        assert login_res.status_code == 200

        view_res = client.get(f"/api/v1/recipient/cases/{case.id}")
        assert view_res.status_code == 200
        data = view_res.json()

        assert data["is_snapshot_backed"] is True
        assert data["is_draft_preview"] is False
        assert data["snapshot_mode"] == "frozen_snapshot"
        assert data["current_version_number"] == 1
        assert len(data["transfer_packs"]) == 1
        assert data["transfer_packs"][0]["name"] == "Core Payment Routing"

        projected_c1 = next(c for c in data["transfer_packs"][0]["claims"] if c["id"] == str(c1.id))
        assert projected_c1["title"] == "Approved Next Action Title"
        assert projected_c1["body_text"] == "Original approved body text."

        # Restricted claim still masked in frozen snapshot view
        projected_restr = next(c for c in data["transfer_packs"][0]["claims"] if c["id"] == str(c_restr.id))
        assert projected_restr["is_restricted_withheld"] is True
        assert "RESTRICTED EVIDENCE" in projected_restr["body_text"]
        assert len(data["access_blockers"]) == 1

        # Acknowledgement updates dynamically without mutating snapshot_json
        ack_res = client.post(f"/api/v1/recipient/cases/{case.id}/acknowledge")
        assert ack_res.status_code == 200
        view_after_ack = client.get(f"/api/v1/recipient/cases/{case.id}").json()
        assert view_after_ack["is_acknowledged"] is True
        session.refresh(v1)
        assert v1.snapshot_json["transfer_packs"][0]["claims"][0]["title"] == "Approved Next Action Title"

        # Tamper hash test -> must return controlled error, NEVER fall back to mutable live DB
        tampered = dict(v1.snapshot_json)
        tampered_packs = list(tampered["transfer_packs"])
        tampered["transfer_packs"] = [{"broken": True}]
        v1.snapshot_json = tampered
        session.commit()

        corrupt_res = client.get(f"/api/v1/recipient/cases/{case.id}")
        assert corrupt_res.status_code == 500
        assert "integrity" in corrupt_res.text.lower()

        # Draft preview test (no approved version) -> clearly labeled as draft preview
        draft_case = HandoverCase(
            id=uuid.uuid4(),
            project_id=project_id,
            case_number=max_num + 2,
            title="Draft Preview Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.DRAFT,
            created_by_id=maya.id,
        )
        session.add(draft_case)
        session.flush()
        session.add(CaseParticipant(case_id=draft_case.id, user_id=aisha.id, role=CaseParticipantRole.RECIPIENT))
        session.commit()

        draft_view = client.get(f"/api/v1/recipient/cases/{draft_case.id}")
        assert draft_view.status_code == 200
        assert draft_view.json()["is_draft_preview"] is True
        assert draft_view.json()["is_snapshot_backed"] is False
    finally:
        session.close()
