"""Shared, authoritative case-source scope and restricted-clearance policy helper.

Single source of truth for:
- Resolving ConnectedSource scope for a HandoverCase (`CaseSource` vs project fallback).
- Checking whether a viewer holds elevated restricted-evidence clearance.
- Applying consistent `[RESTRICTED EVIDENCE]` projection filtering.
"""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.dependencies import get_user_context_capabilities
from app.db.enums import CaseParticipantRole, ProjectRole, WorkspaceRole

RESTRICTED_EVIDENCE_PLACEHOLDER = "[RESTRICTED EVIDENCE — Access clearance required to inspect source details.]"


def resolve_case_source_ids(
    db: Session,
    *,
    case_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Return ConnectedSource IDs explicitly scoped to the case, or project fallback."""
    from app.modules.handover_cases.models import CaseSource, HandoverCase
    from app.modules.sources.models import ConnectedSource

    case_sources = db.query(CaseSource).filter(CaseSource.case_id == case_id).all()
    if case_sources:
        return [cs.connected_source_id for cs in case_sources]

    target_project_id = project_id
    if target_project_id is None:
        case_obj = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
        if not case_obj:
            return []
        target_project_id = case_obj.project_id

    return [
        s.id
        for s in db.query(ConnectedSource)
        .filter(ConnectedSource.project_id == target_project_id)
        .all()
    ]


def has_restricted_clearance(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    case_id: uuid.UUID | None = None,
    user=None,
) -> bool:
    """Evaluate least-privilege clearance for RESTRICTED sources and claim evidence.

    Rules preserved across all modules (Q&A, Sources, RAG, Compliance Exports):
    - Missing membership or RECIPIENT case participation denies restricted access by default.
    - Only Workspace OWNER or Project LEAD (who is NOT a RECIPIENT on the target case)
      receives restricted clearance.
    """
    from app.modules.handover_cases.models import CaseParticipant
    from app.modules.projects.models import Project, ProjectMembership
    from app.modules.workspaces.models import WorkspaceMembership

    if case_id is not None:
        is_recipient = (
            db.query(CaseParticipant)
            .filter(
                CaseParticipant.case_id == case_id,
                CaseParticipant.user_id == user_id,
                CaseParticipant.role == CaseParticipantRole.RECIPIENT,
            )
            .first()
            is not None
        )
        if is_recipient:
            return False

    if user is not None:
        _, ws_roles, proj_roles = get_user_context_capabilities(
            db, user, project_id=project_id, case_id=case_id
        )
        return "OWNER" in ws_roles or proj_roles.get(str(project_id)) == "LEAD"

    proj_obj = db.query(Project).filter(Project.id == project_id).first()
    if not proj_obj:
        return False

    is_ws_owner = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == proj_obj.workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.role == WorkspaceRole.OWNER,
        )
        .first()
        is not None
    )
    if is_ws_owner:
        return True

    is_project_lead = (
        db.query(ProjectMembership)
        .filter(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
            ProjectMembership.role == ProjectRole.LEAD,
        )
        .first()
        is not None
    )
    return is_project_lead


def get_restricted_claim_ids(db: Session, *, claim_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Return claim IDs that reference at least one restricted ClaimEvidence item."""
    from app.modules.evidence.models import ClaimEvidence

    id_list = list(claim_ids)
    if not id_list:
        return set()
    return {
        ce.claim_id
        for ce in db.query(ClaimEvidence.claim_id)
        .filter(
            ClaimEvidence.claim_id.in_(id_list),
            ClaimEvidence.is_restricted.is_(True),
        )
        .all()
    }
