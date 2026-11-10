"""CORS, request-ID, and timing middleware."""

import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
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


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI application.

    CORSMiddleware is added last so it evaluates first on incoming requests,
    handling OPTIONS preflight cleanly for any web origin with credentials.
    """
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TimingMiddleware)

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
