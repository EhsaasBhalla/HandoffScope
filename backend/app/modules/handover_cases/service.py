"""Handover case service — state machine, creation, queries."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransitionError, NotFoundError, ConflictError
from app.db.enums import CaseParticipantRole, CaseStatus, CaseSyncStatus
from app.modules.audit.service import create_audit_event
from app.modules.handover_cases.models import CaseParticipant, HandoverCase

logger = logging.getLogger("handoffscope.cases")


# ── State Machine ─────────────────────────────────────────────
# Maps current status → set of valid next statuses
VALID_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.DRAFT: {CaseStatus.CONNECTING, CaseStatus.CANCELLED},
    CaseStatus.CONNECTING: {CaseStatus.INGESTING, CaseStatus.CANCELLED},
    CaseStatus.INGESTING: {CaseStatus.RECONSTRUCTING, CaseStatus.CANCELLED},
    CaseStatus.RECONSTRUCTING: {
        CaseStatus.NEEDS_INPUT,
        CaseStatus.UNDER_REVIEW,
        CaseStatus.CANCELLED,
    },
    CaseStatus.NEEDS_INPUT: {
        CaseStatus.RECONSTRUCTING,
        CaseStatus.UNDER_REVIEW,
        CaseStatus.CANCELLED,
    },
    CaseStatus.UNDER_REVIEW: {
        CaseStatus.APPROVED,
        CaseStatus.NEEDS_INPUT,
        CaseStatus.RECONSTRUCTING,
        CaseStatus.CANCELLED,
    },
    CaseStatus.APPROVED: {CaseStatus.SHARED, CaseStatus.UNDER_REVIEW},
    CaseStatus.SHARED: {CaseStatus.PARTIALLY_ACKNOWLEDGED, CaseStatus.ACKNOWLEDGED},
    CaseStatus.PARTIALLY_ACKNOWLEDGED: {CaseStatus.ACKNOWLEDGED},
    CaseStatus.ACKNOWLEDGED: {CaseStatus.TRANSFERRED},
    CaseStatus.TRANSFERRED: set(),  # Terminal state
    CaseStatus.CANCELLED: set(),  # Terminal state
}


def can_transition(current: CaseStatus, target: CaseStatus) -> bool:
    """Check if a state transition is valid."""
    return target in VALID_TRANSITIONS.get(current, set())


def get_next_case_number(db: Session, project_id: uuid.UUID) -> int:
    """Get the next sequential case number for a project.

    Uses MAX+1 within a flush to ensure consistency.
    """
    result = (
        db.query(sa_func.max(HandoverCase.case_number))
        .filter(HandoverCase.project_id == project_id)
        .scalar()
    )
    return (result or 0) + 1


def create_case(
    db: Session,
    *,
    project_id: uuid.UUID,
    title: str,
    description: str | None,
    transition_type: str,
    scope_start=None,
    scope_end=None,
    created_by_id: uuid.UUID,
    departing_id: uuid.UUID | None = None,
    reviewer_id: uuid.UUID | None = None,
    recipient_id: uuid.UUID | None = None,
) -> HandoverCase:
    """Create a new handover case in DRAFT status."""
    from app.db.enums import TransitionType

    case_number = get_next_case_number(db, project_id)

    case = HandoverCase(
        project_id=project_id,
        case_number=case_number,
        title=title,
        description=description,
        transition_type=TransitionType(transition_type),
        status=CaseStatus.DRAFT,
        sync_status=CaseSyncStatus.UNKNOWN_FRESHNESS,
        scope_start=scope_start,
        scope_end=scope_end,
        created_by_id=created_by_id,
    )
    db.add(case)
    db.flush()

    # Add initiator as participant
    db.add(CaseParticipant(
        case_id=case.id,
        user_id=created_by_id,
        role=CaseParticipantRole.INITIATOR,
    ))

    # Add departing contributor
    if departing_id:
        db.add(CaseParticipant(
            case_id=case.id,
            user_id=departing_id,
            role=CaseParticipantRole.DEPARTING,
        ))

    # Add reviewer
    if reviewer_id:
        db.add(CaseParticipant(
            case_id=case.id,
            user_id=reviewer_id,
            role=CaseParticipantRole.REVIEWER,
        ))

    # Add recipient
    if recipient_id:
        db.add(CaseParticipant(
            case_id=case.id,
            user_id=recipient_id,
            role=CaseParticipantRole.RECIPIENT,
        ))

    db.flush()

    create_audit_event(
        db,
        actor_id=created_by_id,
        action="case.created",
        entity_type="handover_case",
        entity_id=case.id,
        details={
            "case_number": case_number,
            "title": title,
            "transition_type": transition_type,
        },
        summary=f"Created handover case #{case_number}: {title}",
    )

    return case


def transition_case(
    db: Session,
    *,
    case: HandoverCase,
    target_status: CaseStatus,
    actor_id: uuid.UUID,
    reason: str | None = None,
) -> HandoverCase:
    """Transition a case to a new status, enforcing the state machine."""
    if case.is_blocked and target_status != CaseStatus.CANCELLED:
        raise InvalidTransitionError(
            f"Case #{case.case_number} is blocked: {case.blocked_reason or 'No reason given'}"
        )

    if not can_transition(case.status, target_status):
        raise InvalidTransitionError(
            f"Cannot transition from {case.status.value} to {target_status.value}",
            detail={
                "current_status": case.status.value,
                "target_status": target_status.value,
                "valid_targets": [s.value for s in VALID_TRANSITIONS.get(case.status, set())],
            },
        )

    old_status = case.status
    case.status = target_status
    db.flush()

    create_audit_event(
        db,
        actor_id=actor_id,
        action="case.status_changed",
        entity_type="handover_case",
        entity_id=case.id,
        details={
            "from_status": old_status.value,
            "to_status": target_status.value,
            "reason": reason,
        },
        summary=f"Case #{case.case_number} transitioned {old_status.value} → {target_status.value}",
    )

    logger.info(
        "Case #%d transitioned %s → %s by %s",
        case.case_number, old_status.value, target_status.value, actor_id,
    )
    return case


def add_participant(
    db: Session,
    *,
    case_id: uuid.UUID,
    user_id: uuid.UUID,
    role: CaseParticipantRole,
    actor_id: uuid.UUID,
) -> CaseParticipant:
    """Add a participant to a case."""
    existing = (
        db.query(CaseParticipant)
        .filter(
            CaseParticipant.case_id == case_id,
            CaseParticipant.user_id == user_id,
            CaseParticipant.role == role,
        )
        .first()
    )
    if existing:
        raise ConflictError(f"User already has role {role.value} on this case")

    participant = CaseParticipant(
        case_id=case_id,
        user_id=user_id,
        role=role,
    )
    db.add(participant)
    db.flush()

    create_audit_event(
        db,
        actor_id=actor_id,
        action="case.participant_added",
        entity_type="handover_case",
        entity_id=case_id,
        details={"user_id": str(user_id), "role": role.value},
        summary=f"Added participant {user_id} as {role.value}",
    )
    return participant


def set_blocked(
    db: Session,
    *,
    case: HandoverCase,
    blocked: bool,
    reason: str | None,
    actor_id: uuid.UUID,
) -> HandoverCase:
    """Set or clear the blocked flag on a case."""
    case.is_blocked = blocked
    case.blocked_reason = reason if blocked else None
    db.flush()

    create_audit_event(
        db,
        actor_id=actor_id,
        action="case.blocked" if blocked else "case.unblocked",
        entity_type="handover_case",
        entity_id=case.id,
        details={"blocked": blocked, "reason": reason},
        summary=f"Case #{case.case_number} {'blocked' if blocked else 'unblocked'}: {reason or ''}",
    )
    return case
