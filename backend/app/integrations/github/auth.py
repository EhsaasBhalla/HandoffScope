"""GitHub App authentication — JWT generation and installation token management."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from jose import jwt

from app.core.config import settings

logger = logging.getLogger("handoffscope.github.auth")

ALGORITHM = "RS256"


def create_github_app_jwt() -> str:
    """Create a short-lived JWT for GitHub App authentication.

    Uses the App's private key to sign a JWT with the App ID.
    """
    now = int(time.time())
    payload = {
        "iat": now - 60,  # Issued at (60s in the past for clock drift)
        "exp": now + (10 * 60),  # Expires in 10 minutes
        "iss": settings.GITHUB_APP_ID,
    }

    private_key_path = Path(settings.GITHUB_APP_PRIVATE_KEY_PATH)
    if not private_key_path.exists():
        raise FileNotFoundError(
            f"GitHub App private key not found: {private_key_path}"
        )

    private_key = private_key_path.read_text()
    return jwt.encode(payload, private_key, algorithm=ALGORITHM)
