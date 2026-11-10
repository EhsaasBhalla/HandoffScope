"""Auth API router — login, logout, refresh, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_db
from app.core.security import decode_token, create_access_token, generate_csrf_token
from app.modules.auth.schemas import LoginRequest, TokenResponse, UserResponse
from app.modules.auth.service import authenticate_user, create_tokens_for_user

router = APIRouter(prefix="/auth", tags=["Auth"])

# Cookie settings
_COOKIE_KWARGS = {
    "httponly": True,
    "samesite": "lax",
    "secure": settings.APP_ENV != "development",
    "path": "/",
}


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate and set JWT cookies."""
    user = authenticate_user(db, body.email, body.password)
    tokens = create_tokens_for_user(user)

    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **_COOKIE_KWARGS,
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        **_COOKIE_KWARGS,
    )

    return TokenResponse(
        csrf_token=tokens["csrf_token"],
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
def logout(response: Response):
    """Clear JWT cookies."""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
def me(user=Depends(get_current_active_user)):
    """Return the currently authenticated user."""
    return UserResponse.model_validate(user)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Issue new access token from valid refresh token."""
    from app.modules.workspaces.models import User

    refresh_tok = request.cookies.get("refresh_token")
    if not refresh_tok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    payload = decode_token(refresh_tok)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    new_access = create_access_token({"sub": str(user.id), "email": user.email})
    csrf = generate_csrf_token()

    response.set_cookie(
        key="access_token",
        value=new_access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **_COOKIE_KWARGS,
    )

    return {"message": "Token refreshed", "csrf_token": csrf}
