"""GitHub service — OAuth state management, webhook verification, and installation lifecycle."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import JWTError, jwt

from app.core.config import settings

logger = logging.getLogger("handoffscope.github")


def sign_oauth_state(user_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> str:
    """Create a signed JWT for GitHub OAuth state with optional workspace binding."""
    now = datetime.now(timezone.utc)
    payload = {
        "typ": "github_oauth_state",
        "sub": str(user_id),
        "nonce": secrets.token_urlsafe(12),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    if workspace_id:
        payload["ws"] = str(workspace_id)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def verify_oauth_state(state_token: str | None) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Verify cryptographic signature on OAuth state and return (user_id, workspace_id)."""
    if not state_token:
        raise HTTPException(status_code=400, detail="Missing OAuth state token")
    try:
        payload = jwt.decode(state_token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("typ") != "github_oauth_state":
            raise HTTPException(status_code=400, detail="Invalid OAuth state type")
        user_id = uuid.UUID(str(payload["sub"]))
        raw_ws = payload.get("ws")
        workspace_id = uuid.UUID(str(raw_ws)) if raw_ws else None
        return user_id, workspace_id
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state parameter") from exc
