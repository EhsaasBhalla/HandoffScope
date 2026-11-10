"""API tests for Transfer Pack restructuring, claim movements, and question endpoints."""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.modules.handover_cases.models import HandoverCase
from app.modules.transfer_packs.models import Claim, TransferPack

client = TestClient(app)


def test_pack_restructuring_and_claim_movement():
    # 1. Login as Maya
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_resp.status_code == 200

    session = SessionLocal()
    try:
        case = session.query(HandoverCase).first()
        assert case is not None
        case_id = str(case.id)

        # 2. Create two test transfer packs
        p1_resp = client.post(
            f"/api/v1/cases/{case_id}/transfer-packs",
            json={
                "name": "Frontend Architecture Restructure Pack",
                "description": "Testing pack restructuring workflows",
                "component_area": "frontend",
            },
        )
        assert p1_resp.status_code == 201
        pack1 = p1_resp.json()
        p1_id = pack1["id"]

        p2_resp = client.post(
            f"/api/v1/cases/{case_id}/transfer-packs",
            json={
                "name": "Backend Services Restructure Pack",
                "description": "Destination pack for split/merge tests",
                "component_area": "backend",
            },
        )
        assert p2_resp.status_code == 201
        pack2 = p2_resp.json()
        p2_id = pack2["id"]

        # 3. Find an existing claim or check claim list
        existing_claim = session.query(Claim).first()
        assert existing_claim is not None
        claim_id = str(existing_claim.id)

        # 4. Move claim to pack1
        move_resp = client.post(
            f"/api/v1/transfer-packs/{p1_id}/claims",
            json={"claim_id": claim_id},
        )
        assert move_resp.status_code == 200
        assert move_resp.json()["id"] == p1_id

        # Verify claim is now in pack1
        claim_resp = client.get(f"/api/v1/claims/{claim_id}")
        assert claim_resp.status_code == 200
        assert claim_resp.json()["transfer_pack_id"] == p1_id

        # 5. Patch claim (update priority and body text)
        patch_claim_resp = client.patch(
            f"/api/v1/claims/{claim_id}",
            json={
                "priority": "CRITICAL",
                "body_text": "Updated body text verifying claim human editing capability.",
            },
        )
        assert patch_claim_resp.status_code == 200
        assert patch_claim_resp.json()["priority"] == "CRITICAL"
        assert "human editing" in patch_claim_resp.json()["body_text"]

        # 6. Status transition on pack1 (DRAFT -> READY_FOR_REVIEW)
        status_resp = client.post(
            f"/api/v1/transfer-packs/{p1_id}/status",
            json={"status": "READY_FOR_REVIEW"},
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "READY_FOR_REVIEW"

        # 7. Split pack: Split claim from pack1 into a new pack
        split_resp = client.post(
            f"/api/v1/transfer-packs/{p1_id}/split",
            json={
                "new_pack_name": "Split Child Pack",
                "claim_ids": [claim_id],
                "component_area": "split-module",
            },
        )
        assert split_resp.status_code == 201
        split_pack = split_resp.json()
        assert split_pack["name"] == "Split Child Pack"
        assert split_pack["claims_count"] == 1

        # 8. Merge pack: Merge split pack into pack2
        merge_resp = client.post(
            f"/api/v1/transfer-packs/{p2_id}/merge",
            json={"source_pack_id": split_pack["id"]},
        )
        assert merge_resp.status_code == 200
        assert merge_resp.json()["id"] == p2_id

        # Verify claim is now in pack2
        claim_check = client.get(f"/api/v1/claims/{claim_id}")
        assert claim_check.status_code == 200
        assert claim_check.json()["transfer_pack_id"] == p2_id

    finally:
        session.close()


def test_question_api_full_flow():
    # 1. Login as Maya
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_resp.status_code == 200

    session = SessionLocal()
    try:
        case = session.query(HandoverCase).first()
        case_id = str(case.id)

        # 2. Create question via POST /api/v1/cases/{case_id}/questions
        create_resp = client.post(
            f"/api/v1/cases/{case_id}/questions",
            json={
                "case_id": case_id,
                "question_text": "How do we rotate redis encryption credentials?",
                "why_it_matters": "Security protocol requirement",
                "priority": "HIGH",
            },
        )
        assert create_resp.status_code == 201
        q_data = create_resp.json()
        q_id = q_data["id"]
        assert q_data["status"] == "OPEN"

        # 3. Patch question
        patch_resp = client.patch(
            f"/api/v1/questions/{q_id}",
            json={"priority": "CRITICAL"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["priority"] == "CRITICAL"

        # 4. Answer question
        ans_resp = client.post(
            f"/api/v1/questions/{q_id}/responses",
            json={"response_text": "Run `./scripts/rotate-keys.sh redis-prod` from the bastion host."},
        )
        assert ans_resp.status_code == 200
        assert ans_resp.json()["status"] == "ANSWERED"
        assert len(ans_resp.json()["responses"]) == 1
        resp_id = ans_resp.json()["responses"][0]["id"]

        # 5. Review response via /question-responses/{response_id}/review
        review_resp = client.patch(
            f"/api/v1/question-responses/{resp_id}/review",
            json={"action": "accept", "notes": "Tested in staging."},
        )
        assert review_resp.status_code == 200
        assert review_resp.json()["status"] == "RESOLVED"
    finally:
        session.close()
