"""API tests for Phase 5 — Identity mappings & Timeline endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.db.base import SessionLocal
from app.main import app
from app.modules.projects.models import Project

client = TestClient(app)


def test_identity_and_timeline_endpoints():
    db = SessionLocal()
    project = db.query(Project).first()
    db.close()
    assert project is not None

    # 1. Login as Maya (Project Lead / Admin)
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_resp.status_code == 200

    # 2. Trigger auto-suggest mappings
    auto_resp = client.post(f"/api/v1/projects/{project.id}/identity-mappings/auto-suggest")
    assert auto_resp.status_code == 200
    mappings = auto_resp.json()
    assert isinstance(mappings, list)

    # 3. Get identity coverage
    cov_resp = client.get(f"/api/v1/projects/{project.id}/identity-coverage")
    assert cov_resp.status_code == 200
    coverage = cov_resp.json()
    assert "coverage_percent" in coverage
    assert "total_external_authors" in coverage

    # 4. Get project timeline
    tl_resp = client.get(f"/api/v1/projects/{project.id}/timeline")
    assert tl_resp.status_code == 200
    timeline = tl_resp.json()
    assert "items" in timeline
    assert "event_types" in timeline
    assert "total" in timeline
    assert timeline["total"] >= 0

    # 5. Filter timeline by event_type
    if timeline["event_types"]:
        sample_type = timeline["event_types"][0]
        filtered_resp = client.get(
            f"/api/v1/projects/{project.id}/timeline",
            params={"event_type": sample_type},
        )
        assert filtered_resp.status_code == 200
        filtered_data = filtered_resp.json()
        assert all(i["event_type"] == sample_type for i in filtered_data["items"])
