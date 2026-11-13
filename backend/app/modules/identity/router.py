"""Identity mapping API router.

Phase 5 — Normalisation & Identity.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import RequireCapability, get_current_active_user, get_db
from app.db.enums import IdentityConfidence
from app.modules.identity import service
from app.modules.identity.schemas import (
    IdentityCoverageOut,
    IdentityMappingCreate,
    IdentityMappingOut,
    IdentityMappingUpdate,
)
from app.modules.workspaces.models import User

router = APIRouter(tags=["identity"])


@router.get(
    "/projects/{project_id}/identity-mappings",
    response_model=list[IdentityMappingOut],
    dependencies=[Depends(RequireCapability("identity.view"))],
)
def list_project_identity_mappings(
    project_id: uuid.UUID,
    confidence: IdentityConfidence | None = Query(default=None),
    auto_suggest: bool = Query(default=False, description="If true, runs auto-suggest before listing"),
    db: Session = Depends(get_db),
):
    """List all identity mappings for a project."""
    if auto_suggest:
        return service.auto_suggest_mappings(db, project_id)
    return service.list_mappings(db, project_id, confidence=confidence)


@router.post(
    "/projects/{project_id}/identity-mappings/auto-suggest",
    response_model=list[IdentityMappingOut],
    dependencies=[Depends(RequireCapability("identity.manage"))],
)
def auto_suggest_identity_mappings(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Run auto-suggestion across imported source records to detect and match contributor identities."""
    return service.auto_suggest_mappings(db, project_id)


@router.get(
    "/projects/{project_id}/identity-coverage",
    response_model=IdentityCoverageOut,
    dependencies=[Depends(RequireCapability("identity.view"))],
)
def get_project_identity_coverage(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Return contributor identity mapping statistics and coverage percentage for a project."""
    return service.get_coverage(db, project_id)


@router.post(
    "/projects/{project_id}/identity-mappings",
    response_model=IdentityMappingOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireCapability("identity.manage"))],
)
def create_identity_mapping(
    project_id: uuid.UUID,
    body: IdentityMappingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Manually add or map a contributor identity."""
    return service.create_mapping(db, project_id, body, actor_id=user.id)


@router.patch(
    "/identity-mappings/{mapping_id}",
    response_model=IdentityMappingOut,
    dependencies=[Depends(RequireCapability("identity.manage"))],
)
def update_identity_mapping(
    mapping_id: uuid.UUID,
    body: IdentityMappingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Confirm, reject, or remap an identity mapping."""
    return service.update_mapping(db, mapping_id, actor_id=user.id, update_data=body)
