"""Unit tests for security utilities: password hashing, JWT, CSRF."""

import pytest
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_csrf_token,
)
from fastapi import HTTPException


def test_password_hashing():
    pw = "handoffscope-dev-2026"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_jwt_access_token_creation_and_decode():
    payload = {"sub": "123e4567-e89b-12d3-a456-426614174000", "email": "test@example.test"}
    token = create_access_token(payload)
    decoded = decode_token(token)
    assert decoded["sub"] == payload["sub"]
    assert decoded["email"] == payload["email"]
    assert decoded["type"] == "access"


def test_jwt_refresh_token_creation():
    payload = {"sub": "123e4567-e89b-12d3-a456-426614174000"}
    token = create_refresh_token(payload)
    decoded = decode_token(token)
    assert decoded["type"] == "refresh"


def test_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc:
        decode_token("invalid.jwt.token")
    assert exc.value.status_code == 401


def test_csrf_token_generation():
    t1 = generate_csrf_token()
    t2 = generate_csrf_token()
    assert len(t1) == 64  # 32 bytes hex
    assert t1 != t2
