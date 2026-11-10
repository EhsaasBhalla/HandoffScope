"""API tests for Questions and Responses endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_questions_flow():
    # 1. Login as Maya
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_resp.status_code == 200

    # 2. List all questions
    list_resp = client.get("/api/v1/questions")
    assert list_resp.status_code == 200
    questions = list_resp.json()
    assert isinstance(questions, list)
    assert len(questions) >= 2  # The seeded Zulip questions
