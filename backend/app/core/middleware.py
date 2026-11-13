"""CORS, request-ID, timing, and CSRF middleware."""

import secrets
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every response."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Measure request processing time."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Process-Time"] = str(elapsed_ms)
        return response


class CSRFHeaderValidationMiddleware(BaseHTTPMiddleware):
    """Validate X-CSRF-Token header against csrf_token cookie for state-modifying requests."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            csrf_cookie = request.cookies.get("csrf_token")
            csrf_header = request.headers.get("X-CSRF-Token")
            if csrf_cookie and csrf_header and not secrets.compare_digest(csrf_header.strip(), csrf_cookie.strip()):
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "ForbiddenError", "message": "CSRF token mismatch"}},
                )
        return await call_next(request)


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI application.

    CORSMiddleware is added last so it evaluates first on incoming requests,
    handling OPTIONS preflight cleanly for any web origin with credentials.
    """
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(CSRFHeaderValidationMiddleware)

    # Allow any HTTP/HTTPS origin (Vercel, preview domains, localhost) with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
