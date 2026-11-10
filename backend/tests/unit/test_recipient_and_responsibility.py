"""Unit tests for Phase 9: Recipient Access, Acknowledgement, and Responsibility Transfer."""

import uuid
import pytest

from app.main import app  # noqa: F401
from app.modules.projects.models import Project, ProjectMembership  # noqa: F401
from app.db.enums import (
    CaseStatus,
    ClaimType,
    EvidenceState,
    ResponsibilityAcceptanceStatus,
    TransferPackStatus,
    TransitionType,
)
from app.db.session import SessionLocal
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import HandoverCase
from app.modules.recipients.models import (
    RecipientAcknowledgement,
    ResponsibilityAcceptance,
    ResponsibilityAssignment,
)
from app.modules.recipients.service import (
    accept_responsibility,
    acknowledge_handover,
    assign_responsibility,
    build_recipient_projection,
    decline_responsibility,
)
from app.modules.reviews.models import HandoverVersion
from app.modules.sharing.models import ShareGrant
from app.modules.sharing.service import (
    create_share_grant,
    revoke_share_grant,
)
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


def test_sharing_and_acknowledgement_lifecycle():
    session = SessionLocal()
    try:
        user1 = session.query(User).first()
        user2 = session.query(User).filter(User.id != user1.id).first()
        assert user1 and user2

        from sqlalchemy import func
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == user1.workspace_memberships[0].workspace.projects[0].id).scalar() or 0
        next_case_num = max_num + 1

        case = HandoverCase(
            id=uuid.uuid4(),
            case_number=next_case_num,
            title=f"Sharing Unit Test Case #{next_case_num}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.APPROVED,
            project_id=user1.workspace_memberships[0].workspace.projects[0].id,
            created_by_id=user1.id,
        )
        session.add(case)
        session.flush()

        version = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=1,
            approved_by_id=user1.id,
            snapshot_json={"metadata": {"version": 1}},
            is_current=True,
        )
        session.add(version)
        session.commit()

        # 1. Create Share Grant -> Case transitions from APPROVED to SHARED
        grant = create_share_grant(
            session,
            version_id=version.id,
            recipient_user_id=user2.id,
            granted_by=user1.id,
        )
        assert grant.is_active is True
        session.refresh(case)
        assert case.status == CaseStatus.SHARED

        # 2. Successor Acknowledges Handover -> Case transitions to ACKNOWLEDGED
        ack = acknowledge_handover(session, case_id=case.id, user_id=user2.id)
        assert ack.user_id == user2.id
        assert ack.handover_version_id == version.id
        session.refresh(case)
        assert case.status == CaseStatus.ACKNOWLEDGED

        # 3. Revoke Share Grant
        revoked = revoke_share_grant(session, grant_id=grant.id, revoked_by=user1.id)
        assert revoked.is_active is False
        assert revoked.revoked_at is not None

    finally:
        session.close()


def test_responsibility_acceptance_and_transferred_state():
    session = SessionLocal()
    try:
        user1 = session.query(User).first()
        user2 = session.query(User).filter(User.id != user1.id).first()
        assert user1 and user2

        from sqlalchemy import func
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == user1.workspace_memberships[0].workspace.projects[0].id).scalar() or 0
        next_case_num = max_num + 1

        case = HandoverCase(
            id=uuid.uuid4(),
            case_number=next_case_num,
            title=f"Responsibility Unit Test Case #{next_case_num}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.ACKNOWLEDGED,
            project_id=user1.workspace_memberships[0].workspace.projects[0].id,
            created_by_id=user1.id,
        )
        session.add(case)
        session.flush()

        version = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=1,
            approved_by_id=user1.id,
            snapshot_json={"metadata": {"version": 1}},
            is_current=True,
        )
        session.add(version)
        session.flush()

        pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Backend Auth Engine",
            status=TransferPackStatus.APPROVED,
        )
        session.add(pack)
        session.flush()

        # Add a normal claim and a restricted claim to test projection filtering
        claim1 = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.NEXT_ACTION,
            title="Rotate JWT secret keys",
            body_text="Generate new 256-bit secret every 90 days.",
            evidence_state=EvidenceState.SUPPORTED,
        )
        session.add(claim1)
        session.flush()

        ev1 = ClaimEvidence(
            id=uuid.uuid4(),
            claim_id=claim1.id,
            excerpt="Secret rotation schedule documented in runbook.",
            is_restricted=False,
        )
        session.add(ev1)

        claim2 = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.DECISION,
            title="Proprietary cryptographic salt",
            body_text="Top secret salt algorithm.",
            evidence_state=EvidenceState.SUPPORTED,
        )
        session.add(claim2)
        session.flush()

        ev2 = ClaimEvidence(
            id=uuid.uuid4(),
            claim_id=claim2.id,
            excerpt="Confidential salt formulation.",
            is_restricted=True,
        )
        session.add(ev2)
        session.commit()

        # 1. Assign responsibility to user2
        assignment = assign_responsibility(
            session,
            transfer_pack_id=pack.id,
            assigned_user_id=user2.id,
            assigned_by=user1.id,
            handover_version_id=version.id,
        )
        assert assignment.acceptance.status == ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE

        # 2. Check successor projection (verifying restricted evidence is filtered)
        proj = build_recipient_projection(session, case_id=case.id, user_id=user2.id)
        assert proj.stats["total_packs"] == 1
        assert proj.stats["assigned_packs"] == 1
        assert len(proj.next_actions) == 1
        assert proj.next_actions[0].title == "Rotate JWT secret keys"
        # Restricted claim should have redacted text and be flagged in access blockers
        assert len(proj.access_blockers) >= 1
        restricted_claims = [c for p in proj.transfer_packs for c in p.claims if c.is_restricted_withheld]
        assert len(restricted_claims) == 1
        assert "RESTRICTED EVIDENCE" in restricted_claims[0].body_text

        # 3. Successor accepts responsibility -> Pack becomes ACCEPTED & Case transitions to TRANSFERRED
        accepted_assign = accept_responsibility(
            session,
            assignment_id=assignment.id,
            user_id=user2.id,
        )
        assert accepted_assign.acceptance.status == ResponsibilityAcceptanceStatus.ACCEPTED
        session.refresh(pack)
        assert pack.status == TransferPackStatus.ACCEPTED
        session.refresh(case)
        assert case.status == CaseStatus.TRANSFERRED

    finally:
        session.close()


def test_responsibility_decline_flow():
    session = SessionLocal()
    try:
        user1 = session.query(User).first()
        user2 = session.query(User).filter(User.id != user1.id).first()

        from sqlalchemy import func
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == user1.workspace_memberships[0].workspace.projects[0].id).scalar() or 0
        next_case_num = max_num + 1

        case = HandoverCase(
            id=uuid.uuid4(),
            case_number=next_case_num,
            title=f"Decline Unit Test Case #{next_case_num}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.ACKNOWLEDGED,
            project_id=user1.workspace_memberships[0].workspace.projects[0].id,
            created_by_id=user1.id,
        )
        session.add(case)
        session.flush()

        version = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=1,
            approved_by_id=user1.id,
            snapshot_json={},
            is_current=True,
        )
        session.add(version)
        session.flush()

        pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Unowned Legacy Service",
            status=TransferPackStatus.APPROVED,
        )
        session.add(pack)
        session.commit()

        assignment = assign_responsibility(
            session,
            transfer_pack_id=pack.id,
            assigned_user_id=user2.id,
            assigned_by=user1.id,
            handover_version_id=version.id,
        )

        declined = decline_responsibility(
            session,
            assignment_id=assignment.id,
            user_id=user2.id,
            reason="I do not have access to the production Kubernetes cluster for this service.",
        )
        assert declined.acceptance.status == ResponsibilityAcceptanceStatus.DECLINED
        assert "Kubernetes" in declined.acceptance.decline_reason

    finally:
        session.close()
