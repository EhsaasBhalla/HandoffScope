"""In-process case event bus, single-use SSE stream tickets, and FastAPI SSE endpoint (Round 3).

Deployment note: An in-process asyncio subscriber map delivers events instantaneously within a
single backend worker process (`uvicorn --workers 1` in single-instance hosts like free-tier
Render). Across multi-process deployments without external pub/sub, frontend falls back to
TanStack Query polling seamlessly.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_db, get_user_context_capabilities
from app.modules.handover_cases.models import HandoverCase
from app.modules.reviews.models import HandoverVersion
from app.modules.sharing.models import ShareGrant
from app.modules.workspaces.models import User

router = APIRouter(tags=["Live Collaboration Events (SSE)"])

_TICKET_TTL_SECONDS = 60
_HEARTBEAT_SECONDS = 15.0


class _StreamTicketRegistry:
    """Short-lived, single-use SSE stream tickets preventing long-lived JWTs in URLs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tickets: dict[str, dict[str, Any]] = {}

    def issue(self, *, user_id: uuid.UUID, case_id: uuid.UUID) -> str:
        raw_ticket = secrets.token_urlsafe(32)
        expires_at = time.time() + _TICKET_TTL_SECONDS
        with self._lock:
            now = time.time()
            # Prune expired tickets
            expired = [k for k, v in self._tickets.items() if v["expires_at"] < now]
            for k in expired:
                self._tickets.pop(k, None)
            self._tickets[raw_ticket] = {
                "user_id": user_id,
                "case_id": case_id,
                "expires_at": expires_at,
            }
        return raw_ticket

    def consume(self, *, ticket: str, case_id: uuid.UUID) -> uuid.UUID | None:
        with self._lock:
            entry = self._tickets.pop(ticket, None)
        if not entry:
            return None
        if entry["expires_at"] < time.time():
            return None
        if entry["case_id"] != case_id:
            return None
        return entry["user_id"]


class CaseEventBus:
    """Thread-safe in-process pub/sub fan-out keyed by case_id (metadata payloads only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[uuid.UUID, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def subscribe(self, case_id: uuid.UUID, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        with self._lock:
            self._subscribers.setdefault(case_id, []).append((loop, q))
        return q

    def unsubscribe(self, case_id: uuid.UUID, queue: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(case_id)
            if not subs:
                return
            self._subscribers[case_id] = [(lp, q) for lp, q in subs if q is not queue]
            if not self._subscribers[case_id]:
                self._subscribers.pop(case_id, None)

    def publish(self, *, case_id: uuid.UUID, event_type: str, entity_id: str | None = None) -> None:
        payload = {
            "id": str(uuid.uuid4()),
            "event_type": event_type,
            "case_id": str(case_id),
            "entity_id": entity_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            targets = list(self._subscribers.get(case_id, []))
        for loop, q in targets:
            def _push(target_q: asyncio.Queue = q, item: dict = payload) -> None:
                try:
                    target_q.put_nowait(item)
                except asyncio.QueueFull:
                    pass
            try:
                loop.call_soon_threadsafe(_push)
            except RuntimeError:
                pass


_TICKETS = _StreamTicketRegistry()
CASE_EVENT_BUS = CaseEventBus()


def publish_case_event(*, case_id: uuid.UUID | None, event_type: str, entity_id: str | None = None) -> None:
    """Safely broadcast a lightweight case metadata event (zero restricted text)."""
    if case_id is None:
        return
    CASE_EVENT_BUS.publish(case_id=case_id, event_type=event_type, entity_id=entity_id)


class SseTicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int = _TICKET_TTL_SECONDS
    delivery_scope: str = "single_instance"


@router.post("/cases/{case_id}/events/ticket", response_model=SseTicketResponse)
def issue_sse_stream_ticket(
    case_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Mint a short-lived single-use SSE stream ticket bound to the caller and case."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handover case not found")

    caps, _, _ = get_user_context_capabilities(db, user, case_id=case_id)
    has_share = (
        db.query(ShareGrant)
        .join(HandoverVersion, ShareGrant.handover_version_id == HandoverVersion.id)
        .filter(
            HandoverVersion.case_id == case_id,
            ShareGrant.recipient_user_id == user.id,
            ShareGrant.revoked_at.is_(None),
        )
        .first()
        is not None
    )
    if "case.view" not in caps and not has_share:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to subscribe to this case")

    ticket = _TICKETS.issue(user_id=user.id, case_id=case_id)
    return SseTicketResponse(ticket=ticket)


@router.get("/cases/{case_id}/events/stream")
async def stream_case_events(
    case_id: uuid.UUID,
    request: Request,
    ticket: str = Query(..., min_length=16),
):
    """Stream Server-Sent Events for live case updates using a single-use short-lived ticket."""
    user_id = _TICKETS.consume(ticket=ticket, case_id=case_id)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or already-used SSE stream ticket",
        )

    loop = asyncio.get_running_loop()
    queue = CASE_EVENT_BUS.subscribe(case_id, loop)

    async def _event_generator() -> AsyncGenerator[str, None]:
        try:
            yield f"event: connected\ndata: {json.dumps({'case_id': str(case_id)})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                    yield f"id: {item['id']}\nevent: {item['event_type']}\ndata: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    # Periodic heartbeat keeps Render/reverse proxies from timing out idle SSE sockets
                    yield ": ping\n\n"
        finally:
            CASE_EVENT_BUS.unsubscribe(case_id, queue)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
