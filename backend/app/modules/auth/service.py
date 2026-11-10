"""Auth service — authentication logic, JWT issuance."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_csrf_token,
    hash_password,
    verify_password,
)
from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.auth")


def authenticate_user(db: Session, email: str, password: str) -> User:
    """Verify credentials and return the User or raise."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        logger.warning("Login attempt for unknown email: %s", email)
        raise NotFoundError("Invalid email or password")
    if not verify_password(password, user.password_hash):
        logger.warning("Invalid password for user: %s", email)
        raise NotFoundError("Invalid email or password")
    if not user.is_active:
        logger.warning("Login attempt for deactivated user: %s", email)
        raise NotFoundError("Account is deactivated")
    return user


def create_tokens_for_user(user: User) -> dict:
    """Create access + refresh JWTs and a CSRF token for a user."""
    token_data = {"sub": str(user.id), "email": user.email}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "csrf_token": generate_csrf_token(),
    }


def create_user(db: Session, email: str, display_name: str, password: str) -> User:
    """Create a new user with hashed password."""
    user = User(
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.flush()
    return user
