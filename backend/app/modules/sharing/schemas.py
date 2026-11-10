"""Pydantic schemas for Handover Version Sharing & Share Grants.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CreateShareGrantRequest(BaseModel):
    recipient_user_id: uuid.UUID


class ShareGrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    handover_version_id: uuid.UUID
    version_number: int
    case_id: uuid.UUID
    case_title: str
    recipient_user_id: uuid.UUID
    recipient_name: str
    recipient_email: str
    granted_by: Optional[uuid.UUID] = None
    granter_name: Optional[str] = None
    granted_at: datetime
    revoked_at: Optional[datetime] = None
    is_active: bool
    is_acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
