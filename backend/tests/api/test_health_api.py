"""API tests for system health and readiness."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "HandoffScope"


def test_head_health_for_uptime_bots():
    response = client.head("/health")
    assert response.status_code == 200

    root_resp = client.head("/")
    assert root_resp.status_code == 200
