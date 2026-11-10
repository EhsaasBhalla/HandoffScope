"""Service layer for Handover Version Sharing & Share Grants.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.enums import CaseStatus
from app.modules.audit.service import create_audit_event
from app.modules.handover_cases.models import HandoverCase
from app.modules.projects.models import Project
from app.modules.recipients.models import RecipientAcknowledgement
from app.modules.reviews.models import HandoverVersion
from app.modules.sharing.models import ShareGrant
from app.modules.workspaces.models import User


def create_share_grant(
    db: Session,
    *,
    version_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    granted_by: uuid.UUID,
) -> ShareGrant:
    """Issue a share grant allowing a recipient to access an approved version."""
    version = db.query(HandoverVersion).filter(HandoverVersion.id == version_id).first()
    if not version:
        raise ValueError("Handover version not found")

    recipient = db.query(User).filter(User.id == recipient_user_id).first()
    if not recipient:
        raise ValueError("Recipient user not found")

    # Check for existing active grant
    existing = (
        db.query(ShareGrant)
        .filter(
            ShareGrant.handover_version_id == version_id,
            ShareGrant.recipient_user_id == recipient_user_id,
            ShareGrant.revoked_at.is_(None),
        )
        .first()
    )
    if existing:
        return existing

    grant = ShareGrant(
        id=uuid.uuid4(),
        handover_version_id=version_id,
        recipient_user_id=recipient_user_id,
        granted_by=granted_by,
        granted_at=datetime.now(timezone.utc),
    )
    db.add(grant)

    # Transition case to SHARED if currently APPROVED
    case = db.query(HandoverCase).filter(HandoverCase.id == version.case_id).first()
    if case and case.status == CaseStatus.APPROVED:
        case.status = CaseStatus.SHARED

    db.flush()

    project = db.query(Project).filter(Project.id == case.project_id).first() if case else None

    create_audit_event(
        db,
        actor_id=granted_by,
        action="case.shared",
        entity_type="handover_version",
        entity_id=version.id,
        details={
            "case_id": str(case.id) if case else None,
            "version_number": version.version_number,
            "recipient_user_id": str(recipient.id),
            "recipient_name": recipient.display_name,
        },
        summary=f"Shared Version {version.version_number} of '{case.title if case else ''}' with {recipient.display_name}",
    )

    db.commit()
    db.refresh(grant)
    return grant


def list_version_share_grants(db: Session, *, version_id: uuid.UUID) -> list[ShareGrant]:
    """List all share grants issued for a version."""
    return (
        db.query(ShareGrant)
        .filter(ShareGrant.handover_version_id == version_id)
        .order_by(ShareGrant.granted_at.desc())
        .all()
    )


def list_case_share_grants(db: Session, *, case_id: uuid.UUID) -> list[ShareGrant]:
    """List all share grants issued across all versions of a handover case."""
    return (
        db.query(ShareGrant)
        .join(HandoverVersion, ShareGrant.handover_version_id == HandoverVersion.id)
        .filter(HandoverVersion.case_id == case_id)
        .order_by(ShareGrant.granted_at.desc())
        .all()
    )


def revoke_share_grant(
    db: Session,
    *,
    grant_id: uuid.UUID,
    revoked_by: uuid.UUID,
) -> ShareGrant:
    """Revoke an active share grant."""
    grant = db.query(ShareGrant).filter(ShareGrant.id == grant_id).first()
    if not grant:
        raise ValueError("Share grant not found")

    if grant.revoked_at:
        return grant

    grant.revoked_at = datetime.now(timezone.utc)
    grant.revoked_by = revoked_by

    create_audit_event(
        db,
        actor_id=revoked_by,
        action="case.share_revoked",
        entity_type="share_grant",
        entity_id=grant.id,
        details={
            "handover_version_id": str(grant.handover_version_id),
            "recipient_user_id": str(grant.recipient_user_id),
        },
        summary=f"Revoked share grant for version {grant.version.version_number if grant.version else ''}",
    )

    db.commit()
    db.refresh(grant)
    return grant
