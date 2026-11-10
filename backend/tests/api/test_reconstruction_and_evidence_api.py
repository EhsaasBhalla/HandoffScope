"""API tests for Phase 6 — Reconstruction, Claims, and Evidence endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.db.base import SessionLocal
from app.main import app
from app.modules.handover_cases.models import HandoverCase
from app.modules.transfer_packs.models import Claim, TransferPack

client = TestClient(app)


def test_reconstruction_and_claims_api():
    # 1. Login as Maya
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_resp.status_code == 200

    # 2. Get case
    db = SessionLocal()
    case = db.query(HandoverCase).first()
    db.close()
    assert case is not None

    # 3. Trigger reconstruction
    recon_resp = client.post(f"/api/v1/cases/{case.id}/reconstruct")
    assert recon_resp.status_code == 200
    recon_data = recon_resp.json()
    assert "packs_created" in recon_data
    assert "claims_created" in recon_data
    assert recon_data["status"] == "COMPLETED"

    # 4. List extraction runs
    runs_resp = client.get(f"/api/v1/cases/{case.id}/extraction-runs")
    assert runs_resp.status_code == 200
    runs = runs_resp.json()
    assert len(runs) >= 1

    # 5. List transfer packs for case
    packs_resp = client.get(f"/api/v1/cases/{case.id}/transfer-packs")
    assert packs_resp.status_code == 200
    packs = packs_resp.json()
    assert len(packs) >= 1
    pack = packs[0]

    # 6. List claims for transfer pack
    claims_resp = client.get(f"/api/v1/transfer-packs/{pack['id']}/claims")
    assert claims_resp.status_code == 200
    claims = claims_resp.json()
    assert len(claims) >= 1
    claim = claims[0]

    # 7. Get claim detail with evidence
    detail_resp = client.get(f"/api/v1/claims/{claim['id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert "evidence" in detail
    assert "evidence_state" in detail
    assert "review_state" in detail
