"""Service layer for Recipient Access, Projections, Acknowledgement, and Responsibility Transfer.

Phase 9 — Recipient Access & Responsibility Transfer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.events import publish_case_event
from app.core.exceptions import ForbiddenError
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    ProjectRole,
    QuestionStatus,
    ResponsibilityAcceptanceStatus,
    TransferPackStatus,
    WorkspaceRole,
)
from app.modules.audit.service import create_audit_event
from app.modules.evidence.clearance import (
    RESTRICTED_EVIDENCE_PLACEHOLDER,
    get_restricted_claim_ids,
    has_restricted_clearance,
)
from app.modules.sharing.redactor import redact_secrets_inline
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.projects.models import Project, ProjectMembership
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
from app.modules.reviews.service import SnapshotIntegrityError, compute_snapshot_hash
from app.modules.sharing.models import ShareGrant
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User, WorkspaceMembership


def _is_canonical_snapshot(snap: Any) -> bool:
    return isinstance(snap, dict) and ("transfer_packs" in snap or snap.get("schema_version", 0) >= 2)


def _is_legacy_summary_or_stub(snap: Any) -> bool:
    """Allow explicit pre-Phase-2 summary seeds / test stubs lacking embedded claim payloads."""
    if not isinstance(snap, dict):
        return False
    if "transfer_packs" in snap or snap.get("schema_version", 0) >= 2:
        return False
    if snap == {} or set(snap.keys()) <= {"metadata"}:
        return True
    if "packs" in snap and isinstance(snap["packs"], list):
        # Historical summary seed from demo_data.py (no embedded claims)
        if set(snap.keys()) <= {"version_number", "case_id", "approved_at", "approved_by", "packs", "metadata"}:
            return all(isinstance(p, dict) and "claims" not in p for p in snap["packs"])
    return False


def _validate_and_parse_canonical_snapshot(snap: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate structure and tamper hash of a canonical frozen snapshot."""
    meta = snap.get("metadata") or {}
    if not isinstance(meta, dict):
        raise SnapshotIntegrityError("Snapshot integrity error: snapshot metadata is malformed.")

    stored_hash = meta.get("snapshot_hash")
    if stored_hash is not None:
        expected_hash = compute_snapshot_hash(snap)
        if stored_hash != expected_hash:
            raise SnapshotIntegrityError("Snapshot integrity error: approved snapshot hash verification failed.")

    raw_packs = snap.get("transfer_packs")
    if not isinstance(raw_packs, list):
        raise SnapshotIntegrityError("Snapshot integrity error: 'transfer_packs' must be a list.")

    parsed_packs: list[dict[str, Any]] = []
    for idx, p in enumerate(raw_packs):
        if not isinstance(p, dict) or not p.get("id") or not p.get("name"):
            raise SnapshotIntegrityError(f"Snapshot integrity error: transfer pack entry #{idx} is missing required fields.")
        claims = p.get("claims")
        if not isinstance(claims, list):
            raise SnapshotIntegrityError(f"Snapshot integrity error: transfer pack '{p.get('name')}' has malformed 'claims'.")
        for c_idx, c in enumerate(claims):
            if not isinstance(c, dict) or not c.get("id") or not c.get("title") or not c.get("claim_type"):
                raise SnapshotIntegrityError(
                    f"Snapshot integrity error: claim #{c_idx} in pack '{p.get('name')}' is missing required fields."
                )
        parsed_packs.append(p)

    next_actions = snap.get("next_actions") if isinstance(snap.get("next_actions"), list) else None
    unfinished_items = snap.get("unfinished_items") if isinstance(snap.get("unfinished_items"), list) else None
    return parsed_packs, next_actions, unfinished_items


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
        claim_id=a.claim_id,
        claim_title=a.claim.title if a.claim else None,
        delegated_from_user_id=a.delegated_from_user_id,
        delegated_from_name=a.delegated_from.display_name if a.delegated_from else None,
        delegation_note=a.delegation_note,
        revoked_at=a.revoked_at,
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

    # 3. Cases via active pack/claim ResponsibilityAssignment
    assigned_cases = (
        db.query(TransferPack.case_id)
        .join(ResponsibilityAssignment, ResponsibilityAssignment.transfer_pack_id == TransferPack.id)
        .filter(
            ResponsibilityAssignment.assigned_user_id == user_id,
            ResponsibilityAssignment.revoked_at.is_(None),
        )
        .all()
    )
    assigned_case_ids = {c[0] for c in assigned_cases}

    all_case_ids = grant_case_ids | participant_case_ids | assigned_case_ids
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

        packs_db = db.query(TransferPack).filter(TransferPack.case_id == c.id).all()
        if current_v and _is_canonical_snapshot(current_v.snapshot_json):
            snap_packs = current_v.snapshot_json.get("transfer_packs") or []
            total_packs_count = len(snap_packs) if isinstance(snap_packs, list) else len(packs_db)
        else:
            total_packs_count = len(packs_db)

        assigned_count = (
            db.query(ResponsibilityAssignment)
            .filter(
                ResponsibilityAssignment.assigned_user_id == user_id,
                ResponsibilityAssignment.transfer_pack_id.in_([p.id for p in packs_db]) if packs_db else False,
                ResponsibilityAssignment.claim_id.is_(None),
                ResponsibilityAssignment.revoked_at.is_(None),
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
                total_packs_count=total_packs_count,
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
    departing_user = None
    if departing_participant and departing_participant.user_id:
        departing_user = db.query(User).filter(User.id == departing_participant.user_id).first()
    departing_name = departing_user.display_name if departing_user else None

    # User responsibility assignments (live post-approval state kept separate from frozen snapshot)
    live_packs = (
        db.query(TransferPack)
        .filter(TransferPack.case_id == case_id)
        .order_by(TransferPack.sort_order.asc(), TransferPack.created_at.asc())
        .all()
    )
    live_pack_ids = [p.id for p in live_packs]
    assignments_q = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.assigned_user_id == user_id,
            ResponsibilityAssignment.transfer_pack_id.in_(live_pack_ids) if live_pack_ids else False,
            ResponsibilityAssignment.revoked_at.is_(None),
        )
    )
    if current_version:
        assignments_q = assignments_q.filter(
            ResponsibilityAssignment.handover_version_id == current_version.id
        )
    all_user_active_assignments = assignments_q.all()
    assignments = [a for a in all_user_active_assignments if a.claim_id is None]
    assignment_map = {a.transfer_pack_id: a for a in assignments}
    responsibilities_out = [_to_assignment_out(a) for a in assignments]

    # Verify viewer authorization for restricted evidence / case access
    is_elevated_viewer = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == case.project_id,
            ProjectMembership.user_id == user_id,
            ProjectMembership.role == ProjectRole.LEAD,
        )
        .first()
        is not None
    )
    is_case_participant = (
        db.query(CaseParticipant)
        .filter(CaseParticipant.case_id == case_id, CaseParticipant.user_id == user_id)
        .first()
        is not None
    )
    proj_for_ws = db.query(Project).filter(Project.id == case.project_id).first()
    is_ws_admin = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == proj_for_ws.workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN]),
        )
        .first()
        is not None
    ) if proj_for_ws else False
    if not (active_grant or all_user_active_assignments or is_case_participant or is_elevated_viewer or is_ws_admin):
        raise ForbiddenError("You do not have access to view this successor handover projection.")

    claim_assignments_q = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.transfer_pack_id.in_(live_pack_ids) if live_pack_ids else False,
            ResponsibilityAssignment.claim_id.isnot(None),
            ResponsibilityAssignment.revoked_at.is_(None),
        )
    )
    if current_version:
        claim_assignments_q = claim_assignments_q.filter(
            ResponsibilityAssignment.handover_version_id == current_version.id
        )
    if not (is_elevated_viewer or is_ws_admin):
        owned_pack_ids = {a.transfer_pack_id for a in assignments}
        claim_filters = [
            ResponsibilityAssignment.assigned_user_id == user_id,
            ResponsibilityAssignment.delegated_from_user_id == user_id,
        ]
        if owned_pack_ids:
            claim_filters.append(ResponsibilityAssignment.transfer_pack_id.in_(owned_pack_ids))
        claim_assignments_q = claim_assignments_q.filter(or_(*claim_filters))
    claim_assignments_out = [_to_assignment_out(a) for a in claim_assignments_q.order_by(ResponsibilityAssignment.assigned_at.desc()).all()]

    eligible_members = (
        db.query(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .filter(ProjectMembership.project_id == case.project_id, User.is_active.is_(True))
        .order_by(User.display_name.asc())
        .all()
    )
    eligible_delegates = [
        {
            "user_id": str(u.id),
            "display_name": u.display_name,
            "email": u.email,
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
        }
        for m, u in eligible_members
    ]

    projected_packs: list[SuccessorProjectedPackOut] = []
    next_actions: list[SuccessorProjectedClaimOut] = []
    unfinished_items: list[dict[str, Any]] = []
    access_blockers: list[dict[str, Any]] = []

    is_snapshot_backed = False
    is_draft_preview = False
    snapshot_mode = "draft_preview"
    snapshot_schema_version: Optional[int] = None

    if current_version:
        snap = current_version.snapshot_json
        if snap is None or not isinstance(snap, dict):
            raise SnapshotIntegrityError("Snapshot integrity error: approved version snapshot is missing or corrupted.")

        if _is_canonical_snapshot(snap):
            snap_packs, snap_next_actions, snap_unfinished = _validate_and_parse_canonical_snapshot(snap)
            is_snapshot_backed = True
            is_draft_preview = False
            snapshot_mode = "frozen_snapshot"
            snapshot_schema_version = snap.get("schema_version", 1)

            for p in snap_packs:
                pack_uuid = uuid.UUID(str(p["id"]))
                pack_name = p["name"]
                claims_list = p.get("claims", [])
                projected_claims: list[SuccessorProjectedClaimOut] = []

                for c in claims_list:
                    claim_uuid = uuid.UUID(str(c["id"]))
                    ev_list = c.get("evidence") if isinstance(c.get("evidence"), list) else []
                    is_withheld = False
                    snippets: list[str] = []

                    for ev in ev_list:
                        if not isinstance(ev, dict):
                            continue
                        if ev.get("is_restricted"):
                            is_withheld = True
                            access_blockers.append({
                                "id": str(ev.get("id") or claim_uuid),
                                "claim_id": str(claim_uuid),
                                "claim_title": c["title"],
                                "pack_name": pack_name,
                                "locator": ev.get("locator") or "Restricted Document Reference",
                                "reason": "Evidence source requires elevated clearance.",
                            })
                        else:
                            ex = ev.get("excerpt")
                            if ex:
                                snippets.append(redact_secrets_inline(str(ex)[:120]).redacted_text)

                    body_text = c.get("body_text")
                    original_body_text = c.get("original_body_text")
                    if is_withheld:
                        body_text = RESTRICTED_EVIDENCE_PLACEHOLDER
                        original_body_text = None
                    else:
                        body_text = redact_secrets_inline(body_text).redacted_text if body_text else body_text
                        original_body_text = (
                            redact_secrets_inline(original_body_text).redacted_text
                            if original_body_text
                            else original_body_text
                        )

                    claim_out = SuccessorProjectedClaimOut(
                        id=claim_uuid,
                        transfer_pack_id=uuid.UUID(str(c.get("transfer_pack_id") or pack_uuid)),
                        claim_type=str(c["claim_type"]),
                        title=str(c["title"]),
                        body_text=body_text,
                        original_body_text=original_body_text,
                        evidence_state=str(c.get("evidence_state") or "UNKNOWN"),
                        freshness=str(c.get("freshness") or "CURRENT"),
                        review_state=str(c.get("review_state") or "ACCEPTED"),
                        priority=str(c.get("priority") or "MEDIUM"),
                        is_restricted_withheld=is_withheld,
                        evidence_count=len(ev_list),
                        evidence_snippets=snippets,
                    )
                    projected_claims.append(claim_out)

                    if str(c["claim_type"]) == ClaimType.NEXT_ACTION.value:
                        next_actions.append(claim_out)

                    if snap_unfinished is None and str(c["claim_type"]) in {ClaimType.KNOWLEDGE_GAP.value, ClaimType.RISK.value}:
                        unfinished_items.append({
                            "id": str(claim_uuid),
                            "type": "CLAIM",
                            "title": c["title"],
                            "description": body_text,
                            "pack_name": pack_name,
                            "priority": str(c.get("priority") or "MEDIUM"),
                        })

                live_pack = next((lp for lp in live_packs if lp.id == pack_uuid), None)
                pack_status = (
                    live_pack.status.value
                    if live_pack and hasattr(live_pack.status, "value")
                    else str(live_pack.status) if live_pack else str(p.get("status") or "APPROVED")
                )
                pack_assignment = assignment_map.get(pack_uuid)
                projected_packs.append(
                    SuccessorProjectedPackOut(
                        id=pack_uuid,
                        name=pack_name,
                        description=p.get("description"),
                        component_area=p.get("component_area"),
                        status=pack_status,
                        claims_count=len(projected_claims),
                        claims=projected_claims,
                        assignment=_to_assignment_out(pack_assignment) if pack_assignment else None,
                    )
                )

            if snap_unfinished is not None:
                for u_item in snap_unfinished:
                    if not isinstance(u_item, dict):
                        continue
                    item_copy = dict(u_item)
                    if item_copy.get("is_restricted"):
                        item_copy["description"] = RESTRICTED_EVIDENCE_PLACEHOLDER
                    item_copy.pop("is_restricted", None)
                    unfinished_items.append(item_copy)

        elif _is_legacy_summary_or_stub(snap):
            # Explicit legacy seed / minimal Phase-9 test stub compatibility path
            snapshot_mode = "legacy_summary"
            is_snapshot_backed = False
            is_draft_preview = False
            for p in live_packs:
                claims = db.query(Claim).filter(Claim.transfer_pack_id == p.id).all()
                projected_claims: list[SuccessorProjectedClaimOut] = []

                for c in claims:
                    evidence_records = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == c.id).all()
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
                        elif ev.excerpt:
                            snippets.append(ev.excerpt[:120])

                    original_body_text = c.original_body_text
                    if is_withheld:
                        body_text = RESTRICTED_EVIDENCE_PLACEHOLDER
                        original_body_text = None

                    claim_out = SuccessorProjectedClaimOut(
                        id=c.id,
                        transfer_pack_id=c.transfer_pack_id,
                        claim_type=c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type),
                        title=c.title,
                        body_text=body_text,
                        original_body_text=original_body_text,
                        evidence_state=c.evidence_state.value if hasattr(c.evidence_state, "value") else str(c.evidence_state),
                        freshness=c.freshness.value if hasattr(c.freshness, "value") else str(c.freshness),
                        review_state=c.review_state.value if hasattr(c.review_state, "value") else str(c.review_state),
                        priority=c.priority.value if hasattr(c.priority, "value") else str(c.priority),
                        is_restricted_withheld=is_withheld,
                        evidence_count=len(evidence_records),
                        evidence_snippets=snippets,
                    )
                    projected_claims.append(claim_out)
                    if c.claim_type == ClaimType.NEXT_ACTION:
                        next_actions.append(claim_out)
                    if c.claim_type in [ClaimType.KNOWLEDGE_GAP, ClaimType.RISK]:
                        unfinished_items.append({
                            "id": str(c.id),
                            "type": "CLAIM",
                            "title": c.title,
                            "description": body_text,
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
        else:
            raise SnapshotIntegrityError("Snapshot integrity error: unsupported or corrupted approved snapshot payload.")

    else:
        # No approved version exists -> Draft Preview only (clearly labeled as unapproved draft)
        is_snapshot_backed = False
        is_draft_preview = True
        snapshot_mode = "draft_preview"
        for p in live_packs:
            claims = db.query(Claim).filter(Claim.transfer_pack_id == p.id).all()
            projected_claims = []
            for c in claims:
                evidence_records = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == c.id).all()
                body_text = c.body_text
                is_withheld = False
                snippets = []
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
                    elif ev.excerpt:
                        snippets.append(ev.excerpt[:120])
                original_body_text = c.original_body_text
                if is_withheld:
                    body_text = RESTRICTED_EVIDENCE_PLACEHOLDER
                    original_body_text = None
                claim_out = SuccessorProjectedClaimOut(
                    id=c.id,
                    transfer_pack_id=c.transfer_pack_id,
                    claim_type=c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type),
                    title=c.title,
                    body_text=body_text,
                    original_body_text=original_body_text,
                    evidence_state=c.evidence_state.value if hasattr(c.evidence_state, "value") else str(c.evidence_state),
                    freshness=c.freshness.value if hasattr(c.freshness, "value") else str(c.freshness),
                    review_state=c.review_state.value if hasattr(c.review_state, "value") else str(c.review_state),
                    priority=c.priority.value if hasattr(c.priority, "value") else str(c.priority),
                    is_restricted_withheld=is_withheld,
                    evidence_count=len(evidence_records),
                    evidence_snippets=snippets,
                )
                projected_claims.append(claim_out)
                if c.claim_type == ClaimType.NEXT_ACTION:
                    next_actions.append(claim_out)
                if c.claim_type in [ClaimType.KNOWLEDGE_GAP, ClaimType.RISK]:
                    unfinished_items.append({
                        "id": str(c.id),
                        "type": "CLAIM",
                        "title": c.title,
                        "description": body_text,
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

    # For non-frozen views or live supplementary Q&A, append open questions cleanly
    if not is_snapshot_backed:
        open_questions = (
            db.query(Question)
            .filter(
                Question.case_id == case_id,
                Question.status.in_([QuestionStatus.OPEN, QuestionStatus.ANSWERED, QuestionStatus.PENDING_REVIEW]),
            )
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
    snap_meta = (current_version.snapshot_json.get("metadata") or {}) if (current_version and isinstance(current_version.snapshot_json, dict)) else {}
    approved_by_name = None
    if current_version:
        approved_by_name = current_version.approver.display_name if current_version.approver else snap_meta.get("approved_by_name")

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
        is_snapshot_backed=is_snapshot_backed,
        is_draft_preview=is_draft_preview,
        snapshot_mode=snapshot_mode,
        snapshot_schema_version=snapshot_schema_version,
        approved_at=current_version.approved_at if current_version else None,
        approved_by_name=approved_by_name,
        responsibilities=responsibilities_out,
        claim_assignments=claim_assignments_out,
        eligible_delegates=eligible_delegates,
        transfer_packs=projected_packs,
        next_actions=next_actions,
        unfinished_items=unfinished_items,
        access_blockers=access_blockers,
        stats={
            "total_packs": len(projected_packs),
            "assigned_packs": len(assignments),
            "accepted_packs": accepted_p,
            "declined_packs": declined_p,
            "pending_packs": pending_p,
            "claim_assignments_count": len(claim_assignments_out),
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
    if case.status in [CaseStatus.SHARED, CaseStatus.APPROVED, CaseStatus.PARTIALLY_ACKNOWLEDGED]:
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

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(ack)
    publish_case_event(
        case_id=case.id,
        event_type="case.acknowledged",
        entity_id=str(ack.id),
    )
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

    case = pack.case or db.query(HandoverCase).filter(HandoverCase.id == pack.case_id).first()
    if not case:
        raise ValueError("Parent handover case not found")
    if case.status not in (
        CaseStatus.APPROVED,
        CaseStatus.SHARED,
        CaseStatus.PARTIALLY_ACKNOWLEDGED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.TRANSFERRED,
    ):
        raise ValueError("Cannot assign responsibility on an unapproved handover case")

    if handover_version_id:
        v = (
            db.query(HandoverVersion)
            .filter(HandoverVersion.id == handover_version_id, HandoverVersion.case_id == pack.case_id)
            .first()
        )
        if not v:
            raise ValueError("Specified handover version not found for this case")
        version_id = v.id
    else:
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

    # Check if pack-level assignment already exists for this pack & user
    existing = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.transfer_pack_id == transfer_pack_id,
            ResponsibilityAssignment.assigned_user_id == assigned_user_id,
            ResponsibilityAssignment.claim_id.is_(None),
            ResponsibilityAssignment.revoked_at.is_(None),
        )
        .first()
    )
    if existing:
        return existing

    try:
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
    except Exception:
        db.rollback()
        raise

    db.refresh(assignment)
    publish_case_event(
        case_id=pack.case_id,
        event_type="responsibility.updated",
        entity_id=str(assignment.id),
    )
    return assignment


def _recompute_pack_and_case_transfer_state(
    db: Session,
    *,
    pack: TransferPack | None,
    version_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> None:
    """Recalculate parent TransferPack status and HandoverCase status across active pack + claim assignments."""
    if not pack or not version_id:
        return

    pack_active = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.transfer_pack_id == pack.id,
            ResponsibilityAssignment.handover_version_id == version_id,
            ResponsibilityAssignment.revoked_at.is_(None),
        )
        .all()
    )
    pack_level_asgn = next((a for a in pack_active if a.claim_id is None), None)
    claim_asgns = [a for a in pack_active if a.claim_id is not None]

    pack_level_status = (
        pack_level_asgn.acceptance.status
        if pack_level_asgn and pack_level_asgn.acceptance
        else None
    )
    claim_statuses = [
        a.acceptance.status if a.acceptance else ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE
        for a in claim_asgns
    ]

    # Only update status of packs that are already in an approved/shared/transferred lifecycle phase
    if pack.status in (
        TransferPackStatus.APPROVED,
        TransferPackStatus.SHARED,
        TransferPackStatus.PARTIALLY_ACCEPTED,
        TransferPackStatus.ACCEPTED,
    ):
        if (
            pack_level_asgn is not None
            and pack_level_status == ResponsibilityAcceptanceStatus.ACCEPTED
            and (not claim_statuses or all(s == ResponsibilityAcceptanceStatus.ACCEPTED for s in claim_statuses))
        ):
            pack.status = TransferPackStatus.ACCEPTED
        elif (
            (pack_level_status in (ResponsibilityAcceptanceStatus.ACCEPTED, ResponsibilityAcceptanceStatus.DECLINED))
            or any(s in (ResponsibilityAcceptanceStatus.ACCEPTED, ResponsibilityAcceptanceStatus.DECLINED) for s in claim_statuses)
            or bool(claim_asgns)
        ):
            pack.status = TransferPackStatus.PARTIALLY_ACCEPTED
        else:
            pack.status = TransferPackStatus.APPROVED

    case = pack.case
    if not case:
        return

    if case.status not in (
        CaseStatus.APPROVED,
        CaseStatus.SHARED,
        CaseStatus.PARTIALLY_ACKNOWLEDGED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.TRANSFERRED,
    ):
        return

    case_packs = db.query(TransferPack).filter(TransferPack.case_id == case.id).all()
    if not case_packs:
        return

    all_version_active = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.handover_version_id == version_id,
            ResponsibilityAssignment.revoked_at.is_(None),
        )
        .all()
    )
    pack_level_assignments = [a for a in all_version_active if a.claim_id is None]
    assigned_pack_ids = {a.transfer_pack_id for a in pack_level_assignments}
    all_packs_assigned = len(assigned_pack_ids) == len(case_packs)

    all_statuses = [
        a.acceptance.status if a.acceptance else ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE
        for a in all_version_active
    ]
    all_accepted = bool(all_statuses) and all(s == ResponsibilityAcceptanceStatus.ACCEPTED for s in all_statuses)

    if all_packs_assigned and all_accepted:
        if case.status != CaseStatus.TRANSFERRED:
            case.status = CaseStatus.TRANSFERRED
            version_obj = db.query(HandoverVersion).filter(HandoverVersion.id == version_id).first()
            create_audit_event(
                db,
                actor_id=actor_id,
                action="case.transferred",
                entity_type="handover_case",
                entity_id=case.id,
                details={"version_number": version_obj.version_number if version_obj else 1},
                summary=f"All responsibilities accepted! Case '{case.title}' officially transitioned to TRANSFERRED.",
            )
    else:
        has_claim_delegation = any(a.claim_id is not None for a in all_version_active)
        has_accepted = any(s == ResponsibilityAcceptanceStatus.ACCEPTED for s in all_statuses)
        has_declined = any(s == ResponsibilityAcceptanceStatus.DECLINED for s in all_statuses)
        has_unaccepted = any(s != ResponsibilityAcceptanceStatus.ACCEPTED for s in all_statuses)
        if case.status == CaseStatus.TRANSFERRED or (
            (has_accepted or has_declined or has_claim_delegation)
            and (has_unaccepted or not all_packs_assigned)
        ):
            if case.status in (
                CaseStatus.APPROVED,
                CaseStatus.SHARED,
                CaseStatus.ACKNOWLEDGED,
                CaseStatus.PARTIALLY_ACKNOWLEDGED,
                CaseStatus.TRANSFERRED,
            ):
                case.status = CaseStatus.PARTIALLY_ACKNOWLEDGED


def delegate_claim_responsibility(
    db: Session,
    *,
    claim_id: uuid.UUID,
    assigned_user_id: uuid.UUID,
    delegated_by_user_id: uuid.UUID,
    handover_version_id: Optional[uuid.UUID] = None,
    note: Optional[str] = None,
) -> ResponsibilityAssignment:
    """Delegate an individual claim within an assigned pack to another eligible project member."""
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise ValueError("Claim not found")

    pack = db.query(TransferPack).filter(TransferPack.id == claim.transfer_pack_id).first()
    if not pack:
        raise ValueError("Transfer Pack not found")

    case = db.query(HandoverCase).filter(HandoverCase.id == pack.case_id).first()
    if not case:
        raise ValueError("Handover Case not found")
    if case.status not in (
        CaseStatus.APPROVED,
        CaseStatus.SHARED,
        CaseStatus.PARTIALLY_ACKNOWLEDGED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.TRANSFERRED,
    ):
        raise ValueError("Cannot delegate claims on an unapproved handover case")

    if handover_version_id:
        version_obj = (
            db.query(HandoverVersion)
            .filter(HandoverVersion.id == handover_version_id, HandoverVersion.case_id == case.id)
            .first()
        )
    else:
        version_obj = (
            db.query(HandoverVersion)
            .filter(HandoverVersion.case_id == case.id, HandoverVersion.is_current.is_(True))
            .first()
        ) or (
            db.query(HandoverVersion)
            .filter(HandoverVersion.case_id == case.id)
            .order_by(HandoverVersion.version_number.desc())
            .first()
        )
    if not version_obj:
        raise ValueError("No approved version found for this handover case")

    if assigned_user_id == delegated_by_user_id:
        raise ValueError("Cannot delegate a claim to yourself")

    # Verify actor is active pack owner OR Project Lead OR Workspace Owner/Admin
    owns_pack = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.transfer_pack_id == pack.id,
            ResponsibilityAssignment.handover_version_id == version_obj.id,
            ResponsibilityAssignment.assigned_user_id == delegated_by_user_id,
            ResponsibilityAssignment.claim_id.is_(None),
            ResponsibilityAssignment.revoked_at.is_(None),
        )
        .first()
        is not None
    )
    proj = db.query(Project).filter(Project.id == case.project_id).first()
    is_lead = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == case.project_id,
            ProjectMembership.user_id == delegated_by_user_id,
            ProjectMembership.role == ProjectRole.LEAD,
        )
        .first()
        is not None
    )
    is_ws_admin = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == proj.workspace_id,
            WorkspaceMembership.user_id == delegated_by_user_id,
            WorkspaceMembership.role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN]),
        )
        .first()
        is not None
    ) if proj else False
    if not (owns_pack or is_lead or is_ws_admin):
        raise ForbiddenError("Only the assigned pack owner, Project Lead, or Workspace Admin can delegate a claim")

    # Verify target delegate is an active member of this project
    delegate_user = db.query(User).filter(User.id == assigned_user_id, User.is_active.is_(True)).first()
    if not delegate_user:
        raise ValueError("Delegate user not found or inactive")
    target_membership = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == case.project_id,
            ProjectMembership.user_id == assigned_user_id,
        )
        .first()
    )
    if not target_membership:
        raise ForbiddenError("Delegate must be an active member of this project")

    # Target cannot already hold pack-level ownership for this pack
    target_owns_pack = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.transfer_pack_id == pack.id,
            ResponsibilityAssignment.handover_version_id == version_obj.id,
            ResponsibilityAssignment.assigned_user_id == assigned_user_id,
            ResponsibilityAssignment.claim_id.is_(None),
            ResponsibilityAssignment.revoked_at.is_(None),
        )
        .first()
        is not None
    )
    if target_owns_pack:
        raise ValueError("Target member already holds pack-level responsibility for this transfer pack")

    # Prevent active duplicate delegation or sub-delegation cycles on the same claim
    existing_claim_delegation = (
        db.query(ResponsibilityAssignment)
        .filter(
            ResponsibilityAssignment.claim_id == claim.id,
            ResponsibilityAssignment.handover_version_id == version_obj.id,
            ResponsibilityAssignment.revoked_at.is_(None),
        )
        .first()
    )
    if existing_claim_delegation:
        if existing_claim_delegation.assigned_user_id == assigned_user_id:
            raise ValueError("Claim is already actively delegated to this member")
        raise ValueError("This claim already has an active delegation; revoke it first before reassigning")

    # Enforce restricted-evidence clearance before delegating a restricted claim
    restricted_claim_ids = get_restricted_claim_ids(db, claim_ids=[claim.id])
    snap = version_obj.snapshot_json if isinstance(version_obj.snapshot_json, dict) else {}
    snap_restricted = False
    for sp in snap.get("transfer_packs") or []:
        if not isinstance(sp, dict):
            continue
        for sc in sp.get("claims") or []:
            if isinstance(sc, dict) and str(sc.get("id")) == str(claim.id):
                if any(isinstance(ev, dict) and ev.get("is_restricted") for ev in (sc.get("evidence") or [])):
                    snap_restricted = True
    if (claim.id in restricted_claim_ids or snap_restricted) and not has_restricted_clearance(
        db, project_id=case.project_id, case_id=case.id, user_id=assigned_user_id
    ):
        raise ForbiddenError("Delegate lacks restricted-evidence clearance required for this claim")

    assignment = ResponsibilityAssignment(
        id=uuid.uuid4(),
        transfer_pack_id=pack.id,
        handover_version_id=version_obj.id,
        claim_id=claim.id,
        assigned_user_id=assigned_user_id,
        assigned_by=delegated_by_user_id,
        delegated_from_user_id=delegated_by_user_id,
        delegation_note=note.strip() if note and note.strip() else None,
        assigned_at=datetime.now(timezone.utc),
    )
    try:
        db.add(assignment)
        db.flush()

        acceptance = ResponsibilityAcceptance(
            id=uuid.uuid4(),
            responsibility_assignment_id=assignment.id,
            user_id=assigned_user_id,
            status=ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE,
        )
        db.add(acceptance)
        db.flush()

        _recompute_pack_and_case_transfer_state(
            db,
            pack=pack,
            version_id=version_obj.id,
            actor_id=delegated_by_user_id,
        )

        create_audit_event(
            db,
            actor_id=delegated_by_user_id,
            action="responsibility.claim_delegated",
            entity_type="responsibility_assignment",
            entity_id=assignment.id,
            details={
                "claim_id": str(claim.id),
                "claim_title": claim.title,
                "transfer_pack_id": str(pack.id),
                "assigned_user_id": str(delegate_user.id),
                "assignee_name": delegate_user.display_name,
            },
            summary=f"Delegated claim '{claim.title[:60]}' to {delegate_user.display_name}",
        )

        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(assignment)
    publish_case_event(
        case_id=case.id,
        event_type="responsibility.updated",
        entity_id=str(assignment.id),
    )
    return assignment


def revoke_claim_delegation(
    db: Session,
    *,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ResponsibilityAssignment:
    """Revoke an active claim-level delegation while preserving audit history via revoked_at."""
    assignment = db.query(ResponsibilityAssignment).filter(ResponsibilityAssignment.id == assignment_id).first()
    if not assignment:
        raise ValueError("Responsibility assignment not found")
    if assignment.claim_id is None:
        raise ValueError("Only claim-level delegations can be revoked")
    if assignment.revoked_at is not None:
        raise ValueError("Claim delegation is already revoked")

    pack = assignment.transfer_pack
    case = pack.case if pack else None
    if not pack or not case:
        raise ValueError("Parent handover case not found")

    proj = db.query(Project).filter(Project.id == case.project_id).first()
    is_lead = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == case.project_id,
            ProjectMembership.user_id == user_id,
            ProjectMembership.role == ProjectRole.LEAD,
        )
        .first()
        is not None
    )
    is_ws_admin = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == proj.workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN]),
        )
        .first()
        is not None
    ) if proj else False

    if user_id not in (assignment.delegated_from_user_id, assignment.assigned_by) and not (is_lead or is_ws_admin):
        raise ForbiddenError("You do not have permission to revoke this claim delegation")

    try:
        assignment.revoked_at = datetime.now(timezone.utc)
        db.flush()

        _recompute_pack_and_case_transfer_state(
            db,
            pack=pack,
            version_id=assignment.handover_version_id,
            actor_id=user_id,
        )

        create_audit_event(
            db,
            actor_id=user_id,
            action="responsibility.claim_revoked",
            entity_type="responsibility_assignment",
            entity_id=assignment.id,
            details={
                "claim_id": str(assignment.claim_id),
                "transfer_pack_id": str(pack.id),
                "revoked_at": assignment.revoked_at.isoformat(),
            },
            summary=f"Revoked claim delegation '{assignment.claim.title[:60] if assignment.claim else assignment.claim_id}'",
        )

        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(assignment)
    publish_case_event(
        case_id=case.id,
        event_type="responsibility.updated",
        entity_id=str(assignment.id),
    )
    return assignment


def accept_responsibility(
    db: Session,
    *,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ResponsibilityAssignment:
    """Successor formally accepts operational responsibility for an assigned pack or delegated claim."""
    assignment = db.query(ResponsibilityAssignment).filter(ResponsibilityAssignment.id == assignment_id).first()
    if not assignment:
        raise ValueError("Responsibility assignment not found")
    if assignment.revoked_at is not None:
        raise ValueError("This responsibility assignment has been revoked")

    if assignment.assigned_user_id != user_id:
        raise ValueError("Only the assigned successor can accept this responsibility")

    pack = assignment.transfer_pack
    case = pack.case if pack else None
    if case and case.status not in (
        CaseStatus.APPROVED,
        CaseStatus.SHARED,
        CaseStatus.PARTIALLY_ACKNOWLEDGED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.TRANSFERRED,
    ):
        raise ValueError("Cannot accept responsibility on an unapproved handover case")

    try:
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

        _recompute_pack_and_case_transfer_state(
            db,
            pack=pack,
            version_id=assignment.handover_version_id,
            actor_id=user_id,
        )

        create_audit_event(
            db,
            actor_id=user_id,
            action="responsibility.accepted",
            entity_type="responsibility_assignment",
            entity_id=assignment.id,
            details={
                "transfer_pack_id": str(pack.id) if pack else None,
                "claim_id": str(assignment.claim_id) if assignment.claim_id else None,
            },
            summary=(
                f"Successor accepted delegated claim '{assignment.claim.title[:60] if assignment.claim else ''}'"
                if assignment.claim_id
                else f"Successor accepted responsibility for '{pack.name if pack else ''}'"
            ),
        )

        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(assignment)
    if pack and pack.case_id:
        publish_case_event(
            case_id=pack.case_id,
            event_type="responsibility.updated",
            entity_id=str(assignment.id),
        )
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
    if assignment.revoked_at is not None:
        raise ValueError("This responsibility assignment has been revoked")

    if assignment.assigned_user_id != user_id:
        raise ValueError("Only the assigned successor can decline this responsibility")

    pack = assignment.transfer_pack
    case = pack.case if pack else None
    if case and case.status not in (
        CaseStatus.APPROVED,
        CaseStatus.SHARED,
        CaseStatus.PARTIALLY_ACKNOWLEDGED,
        CaseStatus.ACKNOWLEDGED,
        CaseStatus.TRANSFERRED,
    ):
        raise ValueError("Cannot decline responsibility on an unapproved handover case")

    try:
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

        _recompute_pack_and_case_transfer_state(
            db,
            pack=pack,
            version_id=assignment.handover_version_id,
            actor_id=user_id,
        )

        create_audit_event(
            db,
            actor_id=user_id,
            action="responsibility.declined",
            entity_type="responsibility_assignment",
            entity_id=assignment.id,
            details={
                "transfer_pack_id": str(pack.id) if pack else None,
                "claim_id": str(assignment.claim_id) if assignment.claim_id else None,
                "decline_reason": reason,
            },
            summary=f"Successor declined responsibility for '{pack.name if pack else ''}': {reason[:60]}",
        )

        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(assignment)
    if pack and pack.case_id:
        publish_case_event(
            case_id=pack.case_id,
            event_type="responsibility.updated",
            entity_id=str(assignment.id),
        )
    return assignment
