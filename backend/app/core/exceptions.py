"""Custom exception classes and FastAPI exception handlers."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class HandoffScopeError(Exception):
    """Base exception for all HandoffScope application errors."""

    def __init__(self, message: str, detail: str | dict | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class NotFoundError(HandoffScopeError):
    """Resource not found (404)."""
    pass


class ForbiddenError(HandoffScopeError):
    """Access denied (403)."""
    pass


class ValidationError(HandoffScopeError):
    """Request validation failed (422)."""
    pass


class InvalidTransitionError(HandoffScopeError):
    """Invalid state transition (400)."""
    pass


class ConflictError(HandoffScopeError):
    """Resource conflict — duplicate or concurrent modification (409)."""
    pass


# ── Exception Handlers ───────────────────────────────────────

_STATUS_MAP: dict[type, int] = {
    NotFoundError: 404,
    ForbiddenError: 403,
    ValidationError: 422,
    InvalidTransitionError: 400,
    ConflictError: 409,
    HandoffScopeError: 500,
}


def _build_error_response(code: str, message: str, detail=None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return body


def setup_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on the FastAPI application."""

    @app.exception_handler(HandoffScopeError)
    async def handoffscope_error_handler(request: Request, exc: HandoffScopeError):
        status_code = _STATUS_MAP.get(type(exc), 500)
        code = type(exc).__name__
        return JSONResponse(
            status_code=status_code,
            content=_build_error_response(code, exc.message, exc.detail),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        detail_msg = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
        lowered = detail_msg.lower()
        if "foreign key" in lowered or "not null" in lowered or "check constraint" in lowered:
            status_code = 400
            code = "ValidationError"
        else:
            status_code = 409
            code = "ConflictError"
        return JSONResponse(
            status_code=status_code,
            content=_build_error_response(code, "Database integrity constraint violated", detail=detail_msg),
        )
