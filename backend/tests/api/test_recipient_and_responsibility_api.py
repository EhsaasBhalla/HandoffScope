"""API integration tests for Phase 9: Recipient Access, Acknowledgement, and Responsibility Transfer."""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.enums import CaseStatus, ClaimType, EvidenceState, TransferPackStatus, TransitionType
from app.db.session import SessionLocal
from app.modules.handover_cases.models import HandoverCase
from app.modules.reviews.models import HandoverVersion
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User

client = TestClient(app)


def test_recipient_and_responsibility_api_flow():
    # 1. Login as Maya (Lead / Admin)
    maya_login = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert maya_login.status_code == 200

    session = SessionLocal()
    try:
        user_maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        user_arjun = session.query(User).filter(User.email == "arjun.patel@example.test").first()
        assert user_maya and user_arjun

        from sqlalchemy import func
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == user_maya.workspace_memberships[0].workspace.projects[0].id).scalar() or 0
        next_case_num = max_num + 1

        case = HandoverCase(
            id=uuid.uuid4(),
            case_number=next_case_num,
            title=f"API Recipient Test Case #{next_case_num}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.APPROVED,
            project_id=user_maya.workspace_memberships[0].workspace.projects[0].id,
            created_by_id=user_maya.id,
        )
        session.add(case)
        session.flush()

        version = HandoverVersion(
            id=uuid.uuid4(),
            case_id=case.id,
            version_number=1,
            approved_by_id=user_maya.id,
            snapshot_json={"metadata": {"version": 1}},
            is_current=True,
        )
        session.add(version)
        session.flush()

        pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="API Core Service Pack",
            status=TransferPackStatus.APPROVED,
        )
        session.add(pack)
        session.flush()

        claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.NEXT_ACTION,
            title="Update API gateway routing",
            body_text="Switch route traffic to v2 ingress.",
            evidence_state=EvidenceState.SUPPORTED,
        )
        session.add(claim)
        session.commit()

        case_id = str(case.id)
        version_id = str(version.id)
        pack_id = str(pack.id)
        arjun_id = str(user_arjun.id)

        # 2. Share Version with Arjun via POST /api/v1/versions/{version_id}/share
        share_resp = client.post(
            f"/api/v1/versions/{version_id}/share",
            json={"recipient_user_id": arjun_id},
        )
        assert share_resp.status_code == 201
        share_data = share_resp.json()
        assert share_data["recipient_email"] == "arjun.patel@example.test"
        assert share_data["is_active"] is True

        # 3. Check case share grants via GET /api/v1/cases/{case_id}/shares
        list_shares_resp = client.get(f"/api/v1/cases/{case_id}/shares")
        assert list_shares_resp.status_code == 200
        assert len(list_shares_resp.json()) >= 1

        # 4. Assign pack responsibility to Arjun via POST /api/v1/cases/{case_id}/responsibilities
        assign_resp = client.post(
            f"/api/v1/cases/{case_id}/responsibilities",
            json={
                "transfer_pack_id": pack_id,
                "assigned_user_id": arjun_id,
                "handover_version_id": version_id,
            },
        )
        assert assign_resp.status_code == 201
        assign_data = assign_resp.json()
        assignment_id = assign_data["id"]
        assert assign_data["status"] == "PENDING_ACCEPTANCE"

        # 5. Switch user to Arjun (Successor)
        arjun_login = client.post(
            "/api/v1/auth/login",
            json={"email": "arjun.patel@example.test", "password": "handoffscope-dev-2026"},
        )
        assert arjun_login.status_code == 200

        # 6. Check Arjun's successor cases list via GET /api/v1/recipient/cases
        my_cases_resp = client.get("/api/v1/recipient/cases")
        assert my_cases_resp.status_code == 200
        case_summaries = my_cases_resp.json()
        assert any(c["id"] == case_id for c in case_summaries)

        # 7. Acknowledge Handover via POST /api/v1/recipient/cases/{case_id}/acknowledge
        ack_resp = client.post(f"/api/v1/recipient/cases/{case_id}/acknowledge")
        assert ack_resp.status_code == 200
        ack_data = ack_resp.json()
        assert ack_data["user_id"] == arjun_id

        # 8. Fetch successor continuation view via GET /api/v1/recipient/cases/{case_id}
        view_resp = client.get(f"/api/v1/recipient/cases/{case_id}")
        assert view_resp.status_code == 200
        view_data = view_resp.json()
        assert view_data["is_acknowledged"] is True
        assert len(view_data["responsibilities"]) == 1
        assert len(view_data["next_actions"]) == 1
        assert view_data["stats"]["total_packs"] == 1
        assert view_data["stats"]["assigned_packs"] == 1

        # 9. Accept responsibility via POST /api/v1/responsibility-assignments/{assignment_id}/accept
        accept_resp = client.post(f"/api/v1/responsibility-assignments/{assignment_id}/accept")
        assert accept_resp.status_code == 200
        assert accept_resp.json()["status"] == "ACCEPTED"

        # 10. Verify case transitioned to TRANSFERRED!
        final_view_resp = client.get(f"/api/v1/recipient/cases/{case_id}")
        assert final_view_resp.json()["status"] == "TRANSFERRED"

    finally:
        session.close()
