"""API integration tests for Phase 8: Review Queue, Claim Review, and Version Approval endpoints."""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.enums import CaseStatus, ClaimType, ReviewState, TransferPackStatus, TransitionType
from app.db.session import SessionLocal
from app.modules.handover_cases.models import HandoverCase
from app.modules.transfer_packs.models import Claim, TransferPack

client = TestClient(app)


def test_reviews_and_versions_api_flow():
    # 1. Login as Maya
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_resp.status_code == 200

    session = SessionLocal()
    try:
        # Create an isolated case for this test
        user = session.query(HandoverCase).first()
        from sqlalchemy import func
        max_num = session.query(func.max(HandoverCase.case_number)).filter(HandoverCase.project_id == user.project_id).scalar() or 0
        next_case_num = max_num + 1

        test_case = HandoverCase(
            id=uuid.uuid4(),
            case_number=next_case_num,
            title=f"API Review Queue Test Case #{next_case_num}",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.UNDER_REVIEW,
            project_id=user.project_id,
            created_by_id=user.created_by_id,
        )
        session.add(test_case)
        session.flush()

        test_pack = TransferPack(
            id=uuid.uuid4(),
            case_id=test_case.id,
            name="API Test Pack",
            status=TransferPackStatus.READY_FOR_REVIEW,
        )
        session.add(test_pack)
        session.flush()

        claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=test_pack.id,
            claim_type=ClaimType.DECISION,
            title="Redis Sentinel failover timeout",
            body_text="Failover timeout configured to 5000ms.",
            review_state=ReviewState.PENDING_REVIEW,
        )
        session.add(claim)
        session.commit()

        case_id = str(test_case.id)
        claim_id = str(claim.id)

        # 2. Check Review Queue endpoint
        rq_resp = client.get(f"/api/v1/cases/{case_id}/review-queue")
        assert rq_resp.status_code == 200
        rq_data = rq_resp.json()
        assert rq_data["can_approve"] is False
        assert rq_data["pending_review_count"] == 1
        assert rq_data["total_claims"] == 1

        # 2b. Test case-level claims listing
        case_claims_resp = client.get(f"/api/v1/cases/{case_id}/claims")
        assert case_claims_resp.status_code == 200
        claims_list = case_claims_resp.json()
        assert len(claims_list) == 1
        assert claims_list[0]["id"] == claim_id

        # 3. Review claim - edit_and_accept via PATCH /api/v1/claims/{id}/review
        review_resp = client.patch(
            f"/api/v1/claims/{claim_id}/review",
            json={
                "action": "edit_and_accept",
                "edited_body": "Failover timeout configured to 3000ms for faster reconnect.",
                "reason": "Lowered threshold for high-availability compliance.",
            },
        )
        assert review_resp.status_code == 200
        rev_data = review_resp.json()
        assert rev_data["review_state"] == "EDITED_AND_ACCEPTED"
        assert "3000ms" in rev_data["body_text"]
        assert "5000ms" in rev_data["original_body_text"]

        # 4. Check Review Queue again (now ready to approve!)
        rq_resp2 = client.get(f"/api/v1/cases/{case_id}/review-queue")
        assert rq_resp2.status_code == 200
        assert rq_resp2.json()["can_approve"] is True
        assert rq_resp2.json()["edited_and_accepted_count"] == 1

        # 5. Create approved version via POST /api/v1/cases/{id}/versions
        version_resp = client.post(
            f"/api/v1/cases/{case_id}/versions",
            json={"amendment_reason": "Initial baseline approval."},
        )
        assert version_resp.status_code == 201
        v_data = version_resp.json()
        assert v_data["version_number"] == 1
        assert v_data["is_current"] is True
        assert "snapshot_json" in v_data
        version_id = v_data["id"]

        # 6. List versions via GET /api/v1/cases/{id}/versions
        list_v_resp = client.get(f"/api/v1/cases/{case_id}/versions")
        assert list_v_resp.status_code == 200
        versions_list = list_v_resp.json()
        assert len(versions_list) >= 1
        assert versions_list[0]["version_number"] == 1

        # 7. Get version detail via GET /api/v1/versions/{id}
        detail_resp = client.get(f"/api/v1/versions/{version_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["snapshot_json"]["case"]["title"] == test_case.title
        assert len(detail_data["snapshot_json"]["transfer_packs"]) == 1

    finally:
        session.close()
