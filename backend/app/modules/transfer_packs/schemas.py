"""Transfer pack schemas.

Phase 6 & 7 — Transfer Packs & Claims.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.enums import TransferPackStatus


class TransferPackCreate(BaseModel):
    name: str
    description: Optional[str] = None
    component_area: Optional[str] = None
    recorded_owner_id: Optional[uuid.UUID] = None
    suggested_successor_id: Optional[uuid.UUID] = None


class TransferPackUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    component_area: Optional[str] = None
    status: Optional[TransferPackStatus] = None
    is_blocked: Optional[bool] = None
    blocked_reason: Optional[str] = None
    recorded_owner_id: Optional[uuid.UUID] = None
    suggested_successor_id: Optional[uuid.UUID] = None


class TransferPackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    name: str
    description: Optional[str] = None
    scope_summary: Optional[str] = None
    component_area: Optional[str] = None
    status: TransferPackStatus
    is_blocked: bool = False
    blocked_reason: Optional[str] = None
    recorded_owner_id: Optional[uuid.UUID] = None
    recorded_owner_name: Optional[str] = None
    suggested_successor_id: Optional[uuid.UUID] = None
    suggested_successor_name: Optional[str] = None
    sort_order: int = 0
    claims_count: int = 0
    created_at: datetime
    updated_at: datetime
