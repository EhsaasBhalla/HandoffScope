"""Service layer for Recipient Access, Projections, Acknowledgement, and Responsibility Transfer.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    QuestionStatus,
    ResponsibilityAcceptanceStatus,
    TransferPackStatus,
)
from app.modules.audit.service import create_audit_event
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.projects.models import Project
from app.modules.questions.models import Question
from app.modules.recipients.models import (
    RecipientAcknowledgement,
    ResponsibilityAcceptance,
    ResponsibilityAssignment,
)
from app.modules.recipients.schemas import (
    ResponsibilityAssignmentOut,
    SuccessorCaseSummaryOut,
    SuccessorContinuationViewOut,
    SuccessorProjectedClaimOut,
    SuccessorProjectedPackOut,
)
from app.modules.reviews.models import HandoverVersion
from app.modules.sharing.models import ShareGrant
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


def _to_assignment_out(a: ResponsibilityAssignment) -> ResponsibilityAssignmentOut:
    status_str = (
        a.acceptance.status.value
        if a.acceptance and hasattr(a.acceptance.status, "value")
        else str(a.acceptance.status) if a.acceptance else "PENDING_ACCEPTANCE"
    )
    return ResponsibilityAssignmentOut(
        id=a.id,
        transfer_pack_id=a.transfer_pack_id,
        transfer_pack_name=a.transfer_pack.name if a.transfer_pack else "Unknown Pack",
        transfer_pack_area=a.transfer_pack.component_area if a.transfer_pack else None,
        handover_version_id=a.handover_version_id,
        version_number=a.version.version_number if a.version else 1,
        assigned_user_id=a.assigned_user_id,
        assignee_name=a.assignee.display_name if a.assignee else "Unknown",
        assigned_by=a.assigned_by,
        assigned_at=a.assigned_at,
        status=status_str,
        responded_at=a.acceptance.responded_at if a.acceptance else None,
        decline_reason=a.acceptance.decline_reason if a.acceptance else None,
    )


def list_successor_cases(db: Session, *, user_id: uuid.UUID) -> list[SuccessorCaseSummaryOut]:
    """Find all handover cases shared with or assigned to the successor."""
    # 1. Cases via active Share Grants
    grants = (
        db.query(ShareGrant)
        .filter(ShareGrant.recipient_user_id == user_id, ShareGrant.revoked_at.is_(None))
        .all()
    )
    grant_case_ids = {g.version.case_id for g in grants if g.version}

    # 2. Cases via CaseParticipant RECIPIENT role
    participant_cases = (
        db.query(CaseParticipant.case_id)
        .filter(
            CaseParticipant.user_id == user_id,
            CaseParticipant.role == CaseParticipantRole.RECIPIENT,
        )
        .all()
    )
    participant_case_ids = {c[0] for c in participant_cases}

    all_case_ids = grant_case_ids | participant_case_ids
    if not all_case_ids:
        return []

    cases = (
        db.query(HandoverCase)
        .filter(HandoverCase.id.in_(all_case_ids))
        .order_by(HandoverCase.updated_at.desc())
        .all()
    )

    result = []
    for c in cases:
        current_v = (
            db.query(HandoverVersion)
            .filter(HandoverVersion.case_id == c.id, HandoverVersion.is_current.is_(True))
            .first()
        )
        if not current_v:
            current_v = (
                db.query(HandoverVersion)
                .filter(HandoverVersion.case_id == c.id)
                .order_by(HandoverVersion.version_number.desc())
                .first()
            )

        ack = None
        if current_v:
            ack = (
                db.query(RecipientAcknowledgement)
                .filter(
                    RecipientAcknowledgement.handover_version_id == current_v.id,
                    RecipientAcknowledgement.user_id == user_id,
                )
                .first()
            )

        packs = db.query(TransferPack).filter(TransferPack.case_id == c.id).all()
        assigned_count = (
            db.query(ResponsibilityAssignment)
            .filter(
                ResponsibilityAssignment.assigned_user_id == user_id,
                ResponsibilityAssignment.transfer_pack_id.in_([p.id for p in packs]) if packs else False,
            )
            .count()
        )

        proj = db.query(Project).filter(Project.id == c.project_id).first()
        result.append(
            SuccessorCaseSummaryOut(
                id=c.id,
                case_number=c.case_number,
                title=c.title,
                status=c.status.value if hasattr(c.status, "value") else str(c.status),
                project_name=proj.name if proj else "Project",
                current_version_number=current_v.version_number if current_v else None,
                is_acknowledged=ack is not None,
                acknowledged_at=ack.acknowledged_at if ack else None,
                assigned_packs_count=assigned_count,
                total_packs_count=len(packs),
            )
        )
    return result


def build_recipient_projection(
    db: Session,
    *,
    case_id: uuid.UUID,
    user_id: uuid.UUID,
) -> SuccessorContinuationViewOut:
    """Build a tailored, permission-filtered successor view answering:
    - What am I taking over?
    - What are my next actions?
    - What's unfinished?
    - What do I not have access to?
    """
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError("Handover Case not found")

    # Current or latest version
    current_version = (
        db.query(HandoverVersion)
        .filter(HandoverVersion.case_id == case_id, HandoverVersion.is_current.is_(True))
        .first()
    )
    if not current_version:
        current_version = (
            db.query(HandoverVersion)
            .filter(HandoverVersion.case_id == case_id)
            .order_by(HandoverVersion.version_number.desc())
            .first()
        )

    # Active share grant check
    active_grant = None
    if current_version:
        active_grant = (
            db.query(ShareGrant)
            .filter(
                ShareGrant.handover_version_id == current_version.id,
                ShareGrant.recipient_user_id == user_id,
                ShareGrant.revoked_at.is_(None),
            )
            .first()
        )

    # Acknowledgement status
    ack = None
    if current_version:
        ack = (
            db.query(RecipientAcknowledgement)
            .filter(
                RecipientAcknowledgement.handover_version_id == current_version.id,
                RecipientAcknowledgement.user_id == user_id,
            )
            .first()
        )

    # Fetch departing contributor name
    departing_participant = (
        db.query(CaseParticipant)
        .filter(
            CaseParticipant.case_id == case_id,
            CaseParticipant.role == CaseParticipantRole.DEPARTING,
        )
        .first()
    )
    departing_name = departing_participant.user.display_name if departing_participant and departing_participant.user else None

    # Fetch Transfer Packs
    packs = (
        db.query(TransferPack)
        .filter(TransferPack.case_id == case_id)
        .order_by(TransferPack.created_at.asc())
        .all()
    )

    # User responsibility assignments
    assignments = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.assigned_user_id == user_id,
            ResponsibilityAssignment.transfer_pack_id.in_([p.id for p in packs]) if packs else False,
        )
        .all()
    )
    assignment_map = {a.transfer_pack_id: a for a in assignments}
    responsibilities_out = [_to_assignment_out(a) for a in assignments]

    projected_packs: list[SuccessorProjectedPackOut] = []
    next_actions: list[SuccessorProjectedClaimOut] = []
    unfinished_items: list[dict[str, Any]] = []
    access_blockers: list[dict[str, Any]] = []

    # Iterate over packs & claims
    for p in packs:
        claims = db.query(Claim).filter(Claim.transfer_pack_id == p.id).all()
        projected_claims: list[SuccessorProjectedClaimOut] = []

        for c in claims:
            # Check for restricted evidence
            evidence_records = (
                db.query(ClaimEvidence)
                .filter(ClaimEvidence.claim_id == c.id)
                .all()
            )
            has_restricted_ev = any(ev.is_restricted for ev in evidence_records)

            body_text = c.body_text
            is_withheld = False
            snippets: list[str] = []

            for ev in evidence_records:
                if ev.is_restricted:
                    is_withheld = True
                    access_blockers.append({
                        "id": str(ev.id),
                        "claim_id": str(c.id),
                        "claim_title": c.title,
                        "pack_name": p.name,
                        "locator": ev.locator or "Restricted Document Reference",
                        "reason": "Evidence source requires elevated clearance.",
                    })
                else:
                    if ev.excerpt:
                        snippets.append(ev.excerpt[:120])

            if is_withheld and all(ev.is_restricted for ev in evidence_records) and evidence_records:
                body_text = "[RESTRICTED EVIDENCE — Access clearance required to inspect source details.]"

            claim_out = SuccessorProjectedClaimOut(
                id=c.id,
                transfer_pack_id=c.transfer_pack_id,
                claim_type=c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type),
                title=c.title,
                body_text=body_text,
                original_body_text=c.original_body_text,
                evidence_state=c.evidence_state.value if hasattr(c.evidence_state, "value") else str(c.evidence_state),
                freshness=c.freshness.value if hasattr(c.freshness, "value") else str(c.freshness),
                review_state=c.review_state.value if hasattr(c.review_state, "value") else str(c.review_state),
                priority=c.priority.value if hasattr(c.priority, "value") else str(c.priority),
                is_restricted_withheld=is_withheld,
                evidence_count=len(evidence_records),
                evidence_snippets=snippets,
            )
            projected_claims.append(claim_out)

            # Categorize Next Actions
            if c.claim_type == ClaimType.NEXT_ACTION:
                next_actions.append(claim_out)

            # Categorize Unfinished Items (Knowledge Gaps or high-risk items)
            if c.claim_type in [ClaimType.KNOWLEDGE_GAP, ClaimType.RISK]:
                unfinished_items.append({
                    "id": str(c.id),
                    "type": "CLAIM",
                    "title": c.title,
                    "description": c.body_text,
                    "pack_name": p.name,
                    "priority": c.priority.value if hasattr(c.priority, "value") else str(c.priority),
                })

        pack_assignment = assignment_map.get(p.id)
        projected_packs.append(
            SuccessorProjectedPackOut(
                id=p.id,
                name=p.name,
                description=p.description,
                component_area=p.component_area,
                status=p.status.value if hasattr(p.status, "value") else str(p.status),
                claims_count=len(claims),
                claims=projected_claims,
                assignment=_to_assignment_out(pack_assignment) if pack_assignment else None,
            )
        )

    # Add open questions to unfinished items
    open_questions = (
        db.query(Question)
        .filter(Question.case_id == case_id, Question.status != QuestionStatus.RESOLVED)
        .all()
    )
    for q in open_questions:
        unfinished_items.append({
            "id": str(q.id),
            "type": "QUESTION",
            "title": q.question_text,
            "description": q.why_it_matters or "Unresolved handover question pending response.",
            "pack_name": q.transfer_pack.name if q.transfer_pack else "General Case",
            "priority": q.priority.value if hasattr(q.priority, "value") else str(q.priority),
        })

    # Stats calculation
    accepted_p = sum(1 for a in responsibilities_out if a.status == "ACCEPTED")
    declined_p = sum(1 for a in responsibilities_out if a.status == "DECLINED")
    pending_p = sum(1 for a in responsibilities_out if a.status == "PENDING_ACCEPTANCE")

    proj = db.query(Project).filter(Project.id == case.project_id).first()

    return SuccessorContinuationViewOut(
        case_id=case.id,
        case_number=case.case_number,
        title=case.title,
        transition_type=case.transition_type.value if hasattr(case.transition_type, "value") else str(case.transition_type),
        status=case.status.value if hasattr(case.status, "value") else str(case.status),
        project_id=case.project_id,
        project_name=proj.name if proj else "Project",
        departing_contributor_name=departing_name,
        current_version_number=current_version.version_number if current_version else None,
        version_id=current_version.id if current_version else None,
        is_acknowledged=ack is not None,
        acknowledged_at=ack.acknowledged_at if ack else None,
        share_grant_id=active_grant.id if active_grant else None,
        responsibilities=responsibilities_out,
        transfer_packs=projected_packs,
        next_actions=next_actions,
        unfinished_items=unfinished_items,
        access_blockers=access_blockers,
        stats={
            "total_packs": len(packs),
            "assigned_packs": len(assignments),
            "accepted_packs": accepted_p,
            "declined_packs": declined_p,
            "pending_packs": pending_p,
            "next_actions_count": len(next_actions),
            "access_blockers_count": len(access_blockers),
        },
    )


def acknowledge_handover(
    db: Session,
    *,
    case_id: uuid.UUID,
    user_id: uuid.UUID,
) -> RecipientAcknowledgement:
    """Successor formally acknowledges receipt of the handover case."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError("Handover Case not found")

    current_v = (
        db.query(HandoverVersion)
        .filter(HandoverVersion.case_id == case_id, HandoverVersion.is_current.is_(True))
        .first()
    )
    if not current_v:
        current_v = (
            db.query(HandoverVersion)
            .filter(HandoverVersion.case_id == case_id)
            .order_by(HandoverVersion.version_number.desc())
            .first()
        )
    if not current_v:
        raise ValueError("No approved version exists to acknowledge")

    # Find active share grant
    grant = (
        db.query(ShareGrant)
        .filter(
            ShareGrant.handover_version_id == current_v.id,
            ShareGrant.recipient_user_id == user_id,
            ShareGrant.revoked_at.is_(None),
        )
        .first()
    )
    if not grant:
        # Fallback create active grant if user is case participant
        grant = ShareGrant(
            id=uuid.uuid4(),
            handover_version_id=current_v.id,
            recipient_user_id=user_id,
            granted_by=user_id,
            granted_at=datetime.now(timezone.utc),
        )
        db.add(grant)
        db.flush()

    existing_ack = (
        db.query(RecipientAcknowledgement)
        .filter(
            RecipientAcknowledgement.share_grant_id == grant.id,
            RecipientAcknowledgement.user_id == user_id,
        )
        .first()
    )
    if existing_ack:
        return existing_ack

    ack = RecipientAcknowledgement(
        id=uuid.uuid4(),
        share_grant_id=grant.id,
        handover_version_id=current_v.id,
        user_id=user_id,
        acknowledged_at=datetime.now(timezone.utc),
    )
    db.add(ack)

    # State machine transition: SHARED -> ACKNOWLEDGED / PARTIALLY_ACKNOWLEDGED
    if case.status in [CaseStatus.SHARED, CaseStatus.APPROVED]:
        all_grants = (
            db.query(ShareGrant)
            .filter(ShareGrant.handover_version_id == current_v.id, ShareGrant.revoked_at.is_(None))
            .all()
        )
        ack_count = (
            db.query(RecipientAcknowledgement)
            .filter(RecipientAcknowledgement.handover_version_id == current_v.id)
            .count()
        )
        # Note: including the new one being added (+1)
        if (ack_count + 1) >= len(all_grants):
            case.status = CaseStatus.ACKNOWLEDGED
        else:
            case.status = CaseStatus.PARTIALLY_ACKNOWLEDGED

    create_audit_event(
        db,
        actor_id=user_id,
        action="case.acknowledged",
        entity_type="handover_case",
        entity_id=case.id,
        details={
            "version_number": current_v.version_number,
            "share_grant_id": str(grant.id),
        },
        summary=f"Successor acknowledged receipt of '{case.title}' (Version {current_v.version_number})",
    )

    db.commit()
    db.refresh(ack)
    return ack


def assign_responsibility(
    db: Session,
    *,
    transfer_pack_id: uuid.UUID,
    assigned_user_id: uuid.UUID,
    assigned_by: uuid.UUID,
    handover_version_id: Optional[uuid.UUID] = None,
) -> ResponsibilityAssignment:
    """Assign operational responsibility for a Transfer Pack to a successor."""
    pack = db.query(TransferPack).filter(TransferPack.id == transfer_pack_id).first()
    if not pack:
        raise ValueError("Transfer Pack not found")

    version_id = handover_version_id
    if not version_id:
        v = (
            db.query(HandoverVersion)
            .filter(HandoverVersion.case_id == pack.case_id, HandoverVersion.is_current.is_(True))
            .first()
        )
        if not v:
            v = (
                db.query(HandoverVersion)
                .filter(HandoverVersion.case_id == pack.case_id)
                .order_by(HandoverVersion.version_number.desc())
                .first()
            )
        if not v:
            raise ValueError("No approved version found for this handover case")
        version_id = v.id

    assignee = db.query(User).filter(User.id == assigned_user_id).first()
    if not assignee:
        raise ValueError("Assignee user not found")

    # Check if assignment already exists for this pack & user
    existing = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.transfer_pack_id == transfer_pack_id,
            ResponsibilityAssignment.assigned_user_id == assigned_user_id,
        )
        .first()
    )
    if existing:
        return existing

    assignment = ResponsibilityAssignment(
        id=uuid.uuid4(),
        transfer_pack_id=transfer_pack_id,
        handover_version_id=version_id,
        assigned_user_id=assigned_user_id,
        assigned_by=assigned_by,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(assignment)
    db.flush()

    acceptance = ResponsibilityAcceptance(
        id=uuid.uuid4(),
        responsibility_assignment_id=assignment.id,
        user_id=assigned_user_id,
        status=ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE,
    )
    db.add(acceptance)

    create_audit_event(
        db,
        actor_id=assigned_by,
        action="responsibility.assigned",
        entity_type="responsibility_assignment",
        entity_id=assignment.id,
        details={
            "transfer_pack_id": str(pack.id),
            "transfer_pack_name": pack.name,
            "assigned_user_id": str(assignee.id),
            "assignee_name": assignee.display_name,
        },
        summary=f"Assigned responsibility for '{pack.name}' to {assignee.display_name}",
    )

    db.commit()
    db.refresh(assignment)
    return assignment


def accept_responsibility(
    db: Session,
    *,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ResponsibilityAssignment:
    """Successor formally accepts operational responsibility for an assigned pack."""
    assignment = db.query(ResponsibilityAssignment).filter(ResponsibilityAssignment.id == assignment_id).first()
    if not assignment:
        raise ValueError("Responsibility assignment not found")

    if assignment.assigned_user_id != user_id:
        raise ValueError("Only the assigned successor can accept this responsibility")

    acceptance = assignment.acceptance
    if not acceptance:
        acceptance = ResponsibilityAcceptance(
            id=uuid.uuid4(),
            responsibility_assignment_id=assignment.id,
            user_id=user_id,
            status=ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE,
        )
        db.add(acceptance)

    acceptance.status = ResponsibilityAcceptanceStatus.ACCEPTED
    acceptance.responded_at = datetime.now(timezone.utc)
    acceptance.decline_reason = None

    # Update Transfer Pack status
    pack = assignment.transfer_pack
    if pack:
        pack.status = TransferPackStatus.ACCEPTED

    # Check all assignments for this case/version: if all accepted, transition case to TRANSFERRED!
    case = pack.case if pack else None
    if case and assignment.handover_version_id:
        case_assignments = (
            db.query(ResponsibilityAssignment)
            .filter(ResponsibilityAssignment.handover_version_id == assignment.handover_version_id)
            .all()
        )
        all_accepted = all(
            a.acceptance and a.acceptance.status == ResponsibilityAcceptanceStatus.ACCEPTED
            for a in case_assignments
        )
        if all_accepted and len(case_assignments) > 0:
            case.status = CaseStatus.TRANSFERRED
            create_audit_event(
                db,
                actor_id=user_id,
                action="case.transferred",
                entity_type="handover_case",
                entity_id=case.id,
                details={"version_number": assignment.version.version_number if assignment.version else 1},
                summary=f"All responsibilities accepted! Case '{case.title}' officially transitioned to TRANSFERRED.",
            )

    create_audit_event(
        db,
        actor_id=user_id,
        action="responsibility.accepted",
        entity_type="responsibility_assignment",
        entity_id=assignment.id,
        details={"transfer_pack_id": str(pack.id) if pack else None},
        summary=f"Successor accepted responsibility for '{pack.name if pack else ''}'",
    )

    db.commit()
    db.refresh(assignment)
    return assignment


def decline_responsibility(
    db: Session,
    *,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
) -> ResponsibilityAssignment:
    """Successor formally declines responsibility with a documented reason."""
    assignment = db.query(ResponsibilityAssignment).filter(ResponsibilityAssignment.id == assignment_id).first()
    if not assignment:
        raise ValueError("Responsibility assignment not found")

    if assignment.assigned_user_id != user_id:
        raise ValueError("Only the assigned successor can decline this responsibility")

    acceptance = assignment.acceptance
    if not acceptance:
        acceptance = ResponsibilityAcceptance(
            id=uuid.uuid4(),
            responsibility_assignment_id=assignment.id,
            user_id=user_id,
            status=ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE,
        )
        db.add(acceptance)

    acceptance.status = ResponsibilityAcceptanceStatus.DECLINED
    acceptance.responded_at = datetime.now(timezone.utc)
    acceptance.decline_reason = reason

    pack = assignment.transfer_pack
    if pack:
        pack.status = TransferPackStatus.PARTIALLY_ACCEPTED

    create_audit_event(
        db,
        actor_id=user_id,
        action="responsibility.declined",
        entity_type="responsibility_assignment",
        entity_id=assignment.id,
        details={
            "transfer_pack_id": str(pack.id) if pack else None,
            "decline_reason": reason,
        },
        summary=f"Successor declined responsibility for '{pack.name if pack else ''}': {reason[:60]}",
    )

    db.commit()
    db.refresh(assignment)
    return assignment
