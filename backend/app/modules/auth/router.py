"""Auth API router — login, logout, refresh, me."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_db, get_user_context_capabilities
from app.core.security import decode_token, create_access_token, generate_csrf_token
from app.modules.auth.schemas import LoginRequest, RefreshRequest, TokenResponse, UserResponse
from app.modules.auth.service import authenticate_user, create_tokens_for_user

router = APIRouter(prefix="/auth", tags=["Auth"])


def _cookie_kwargs_for_request(request: Request) -> dict:
    """Resolve cookie flags dynamically so HTTPS proxy deployments always use SameSite=None; Secure."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    is_https = proto == "https" or settings.APP_ENV != "development"
    return {
        "httponly": True,
        "samesite": "none" if is_https else "lax",
        "secure": is_https,
        "path": "/",
    }


def _build_user_response(db: Session, user) -> UserResponse:
    caps, ws_roles, proj_roles = get_user_context_capabilities(db, user)
    base = UserResponse.model_validate(user)
    base.workspace_roles = sorted(set(ws_roles))
    base.project_roles = proj_roles
    base.capabilities = sorted(caps)
    return base


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticate and set JWT cookies (plus token fields for bearer fallback)."""
    user = authenticate_user(db, body.email, body.password)
    tokens = create_tokens_for_user(user)
    cookie_kwargs = _cookie_kwargs_for_request(request)

    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )

    return TokenResponse(
        csrf_token=tokens["csrf_token"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        user=_build_user_response(db, user),
    )


@router.post("/logout")
def logout(request: Request, response: Response):
    """Clear JWT cookies."""
    cookie_kwargs = _cookie_kwargs_for_request(request)
    response.delete_cookie(
        "access_token",
        path=cookie_kwargs["path"],
        samesite=cookie_kwargs["samesite"],
        secure=cookie_kwargs["secure"],
    )
    response.delete_cookie(
        "refresh_token",
        path=cookie_kwargs["path"],
        samesite=cookie_kwargs["samesite"],
        secure=cookie_kwargs["secure"],
    )
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
def me(user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Return the currently authenticated user with authoritative RBAC capabilities."""
    return _build_user_response(db, user)


@router.post("/refresh")
def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """Issue new access token from valid refresh cookie or body/header fallback."""
    from app.modules.workspaces.models import User

    refresh_tok = (
        request.cookies.get("refresh_token")
        or (body.refresh_token if body and body.refresh_token else None)
        or request.headers.get("X-Refresh-Token")
    )
    if not refresh_tok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    payload = decode_token(refresh_tok)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    import uuid

    try:
        user_uuid = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject in token")

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    new_access = create_access_token({"sub": str(user.id), "email": user.email})
    csrf = generate_csrf_token()
    cookie_kwargs = _cookie_kwargs_for_request(request)

    response.set_cookie(
        key="access_token",
        value=new_access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )

    return {"message": "Token refreshed", "csrf_token": csrf, "access_token": new_access}
