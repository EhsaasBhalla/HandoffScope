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


def test_cors_options_preflight_for_vercel():
    headers = {
        "Origin": "https://handoffscope.vercel.app",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, X-CSRF-Token",
    }
    response = client.options("/api/v1/auth/login", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://handoffscope.vercel.app"
    assert response.headers["access-control-allow-credentials"] == "true"
