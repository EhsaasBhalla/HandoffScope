"""Shared FastAPI dependencies: auth, DB session, permission checks."""

from __future__ import annotations

import uuid
from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.base import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session, closing it after the request."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Extract the authenticated user from JWT cookie or Authorization Bearer header.

    Returns the User ORM instance or raises 401.
    """
    # Import here to avoid circular dependency at module load time
    from app.modules.workspaces.models import User

    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — no access token cookie or bearer token",
        )

    payload = decode_token(token)
    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id_str = payload.get("sub")
    try:
        user_id = uuid.UUID(user_id_str)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        ) from exc

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


def get_current_active_user(user=Depends(get_current_user)):
    """Ensure the authenticated user account is active."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return user


# ── RBAC Capability Matrix ────────────────────────────────────
# 9 roles × 30 capabilities — evaluation order per the RBAC doc:
# 1. Auth check (get_current_active_user)
# 2. Workspace role check
# 3. Project role check
# 4. Case participation check
# 5. Resource-level check (sensitivity, ownership)

# Capabilities granted to each workspace role
_WS_CAPABILITIES: dict[str, set[str]] = {
    "OWNER": {
        "workspace.manage", "workspace.view", "workspace.members.manage",
        "project.create", "project.view", "project.manage", "project.members.manage",
        "case.view", "case.create", "case.manage", "case.approve", "case.approve_override",
        "source.connect", "source.view", "source.import", "source.cleanup",
        "extraction.trigger", "extraction.view",
        "pack.create", "pack.view", "pack.manage",
        "review.request", "review.submit", "review.view",
        "question.create", "question.view", "question.answer", "question.review", "question.generate_ai",
        "share.manage", "share.view",
        "document.upload", "document.view",
        "audit.view", "timeline.view",
    },
    "ADMIN": {
        "workspace.view", "workspace.members.manage",
        "project.create", "project.view", "project.manage", "project.members.manage",
        "case.view", "case.create",
        "source.view", "timeline.view", "document.view",
        "audit.view",
    },
    "MEMBER": {
        "workspace.view",
        "project.view",
        "case.view",
        "timeline.view",
    },
}

# Capabilities granted to each project role
_PROJ_CAPABILITIES: dict[str, set[str]] = {
    "LEAD": {
        "project.view", "project.manage", "project.members.manage",
        "case.create", "case.view", "case.manage", "case.participants.manage",
        "case.approve", "case.approve_override",
        "source.connect", "source.view", "source.import", "source.cleanup",
        "extraction.trigger", "extraction.view",
        "pack.create", "pack.view", "pack.manage",
        "review.request", "review.submit", "review.view",
        "question.create", "question.view", "question.answer", "question.review", "question.generate_ai",
        "share.manage", "share.view",
        "identity.manage", "identity.view",
        "document.upload", "document.view",
        "audit.view", "timeline.view",
    },
    "CONTRIBUTOR": {
        "project.view",
        "case.view",
        "source.view",
        "extraction.view",
        "pack.view",
        "review.view",
        "share.view",
        "identity.view",
        "document.view",
        "question.view",
        "timeline.view",
    },
    "REVIEWER": {
        "project.view",
        "case.view",
        "source.view",
        "extraction.view",
        "pack.view",
        "pack.manage",
        "review.submit", "review.view", "case.approve",
        "share.view",
        "identity.view",
        "document.view",
        "question.create", "question.view", "question.review", "question.generate_ai",
        "audit.view", "timeline.view",
    },
}

# Capabilities granted to each case participation role
_CASE_CAPABILITIES: dict[str, set[str]] = {
    "INITIATOR": {
        "case.manage", "case.participants.manage", "case.view",
        "source.connect", "source.import", "source.view",
        "extraction.trigger", "extraction.view",
        "pack.create", "pack.manage", "pack.view",
        "review.request", "review.view",
        "question.create", "question.view", "question.review", "question.generate_ai",
        "share.manage", "share.view",
    },
    "DEPARTING": {
        "case.view",
        "source.view",
        "extraction.view",
        "pack.view",
        "question.view", "question.answer", "question.generate_ai",
        "document.view",
    },
    "REVIEWER": {
        "case.view",
        "review.submit", "review.view", "case.approve",
        "question.create", "question.view", "question.review", "question.generate_ai",
        "pack.view",
        "extraction.view",
        "document.view",
    },
    "RECIPIENT": {
        "case.view",
        "pack.view",
        "question.create", "question.view", "question.generate_ai",
        "acceptance.manage",
        "successor.view",
        "document.view",
    },
    "CONTRIBUTOR": {
        "case.view",
        "source.view",
        "pack.view",
        "question.view",
    },
    "AUDITOR": {
        "case.view",
        "audit.view",
        "pack.view",
        "review.view",
        "extraction.view",
        "question.view",
    },
}


def get_user_context_capabilities(
    db: Session,
    user,
    *,
    project_id: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
) -> tuple[set[str], list[str], dict[str, str]]:
    """Compute server-side RBAC capabilities, workspace roles, and project roles cleanly."""
    from app.modules.workspaces.models import WorkspaceMembership
    from app.modules.projects.models import Project, ProjectMembership
    from app.modules.handover_cases.models import CaseParticipant, HandoverCase

    caps: set[str] = set()
    ws_roles: list[str] = []
    proj_roles: dict[str, str] = {}

    target_project_id = project_id
    target_workspace_id: uuid.UUID | None = None

    if case_id is not None:
        case_obj = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
        if not case_obj:
            return set(), [], {}
        target_project_id = case_obj.project_id

    if target_project_id is not None:
        proj_obj = db.query(Project).filter(Project.id == target_project_id).first()
        if not proj_obj:
            return set(), [], {}
        target_workspace_id = proj_obj.workspace_id

    ws_q = db.query(WorkspaceMembership).filter(WorkspaceMembership.user_id == user.id)
    if target_workspace_id is not None:
        ws_q = ws_q.filter(WorkspaceMembership.workspace_id == target_workspace_id)
    ws_memberships = ws_q.all()
    for wm in ws_memberships:
        ws_roles.append(wm.role.value)
        caps.update(_WS_CAPABILITIES.get(wm.role.value, set()))

    pm_q = db.query(ProjectMembership).filter(ProjectMembership.user_id == user.id)
    if target_project_id is not None:
        pm_q = pm_q.filter(ProjectMembership.project_id == target_project_id)
    for pm in pm_q.all():
        proj_roles[str(pm.project_id)] = pm.role.value
        caps.update(_PROJ_CAPABILITIES.get(pm.role.value, set()))

    if case_id is not None:
        participants = (
            db.query(CaseParticipant)
            .filter(CaseParticipant.user_id == user.id, CaseParticipant.case_id == case_id)
            .all()
        )
        for cp in participants:
            caps.update(_CASE_CAPABILITIES.get(cp.role.value, set()))
        # A user who is DEPARTING on a case must not self-approve/override their own handover
        if any(cp.role.value == "DEPARTING" for cp in participants) and "OWNER" not in ws_roles:
            if target_project_id and proj_roles.get(str(target_project_id)) != "LEAD":
                caps.discard("case.approve")
                caps.discard("case.approve_override")
                caps.discard("review.submit")
    elif project_id is None:
        for cp in db.query(CaseParticipant).filter(CaseParticipant.user_id == user.id).all():
            caps.update(_CASE_CAPABILITIES.get(cp.role.value, set()))

    return caps, ws_roles, proj_roles


def require_case_capability(db: Session, user, case_id: uuid.UUID, capability: str) -> None:
    """Enforce a case-scoped RBAC capability on the backend (raises 403/404 cleanly)."""
    from app.modules.handover_cases.models import HandoverCase

    case_obj = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handover case not found")
    caps, _, _ = get_user_context_capabilities(db, user, case_id=case_id)
    if capability not in caps:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required capability '{capability}' for handover case",
        )


def require_project_capability(db: Session, user, project_id: uuid.UUID, capability: str) -> None:
    """Enforce a project-scoped RBAC capability on the backend."""
    from app.modules.projects.models import Project

    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    caps, _, _ = get_user_context_capabilities(db, user, project_id=project_id)
    if capability not in caps:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required capability '{capability}' for project",
        )


class RequireCapability:
    """Parameterised dependency that checks a user capability.

    Usage::

        @router.get("/...", dependencies=[Depends(RequireCapability("project.view"))])
        def my_endpoint(...): ...
    """

    def __init__(self, capability: str):
        self.capability = capability

    def __call__(
        self,
        request: Request,
        user=Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ):
        if not self._check(db, user, self.capability, request.path_params):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required capability: {self.capability}",
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _check(db: Session, user, capability: str, path_params: dict) -> bool:
        """Evaluate permission strictly within resolved workspace/project/case scope."""
        project_id = None
        case_id = None

        raw_proj = path_params.get("project_id")
        if raw_proj:
            try:
                project_id = uuid.UUID(str(raw_proj))
            except (TypeError, ValueError):
                project_id = None

        raw_case = path_params.get("case_id")
        if raw_case:
            try:
                case_id = uuid.UUID(str(raw_case))
            except (TypeError, ValueError):
                case_id = None

        # Resolve parent case/project from nested entity IDs when direct params omitted
        if case_id is None and path_params.get("question_id"):
            from app.modules.questions.models import Question
            try:
                q = db.query(Question).filter(Question.id == uuid.UUID(str(path_params["question_id"]))).first()
                if q:
                    case_id = q.case_id
            except (TypeError, ValueError):
                pass
        if case_id is None and path_params.get("claim_id"):
            from app.modules.transfer_packs.models import Claim, TransferPack
            try:
                c = db.query(Claim).filter(Claim.id == uuid.UUID(str(path_params["claim_id"]))).first()
                if c and c.transfer_pack_id:
                    tp = db.query(TransferPack).filter(TransferPack.id == c.transfer_pack_id).first()
                    if tp:
                        case_id = tp.case_id
            except (TypeError, ValueError):
                pass
        if project_id is None and path_params.get("source_id"):
            from app.modules.sources.models import ConnectedSource
            try:
                s = db.query(ConnectedSource).filter(ConnectedSource.id == uuid.UUID(str(path_params["source_id"]))).first()
                if s:
                    project_id = s.project_id
            except (TypeError, ValueError):
                pass
        if project_id is None and path_params.get("document_id"):
            from app.modules.documents.models import Document
            try:
                d = db.query(Document).filter(Document.id == uuid.UUID(str(path_params["document_id"]))).first()
                if d:
                    project_id = d.project_id
            except (TypeError, ValueError):
                pass
        if project_id is None and path_params.get("mapping_id"):
            from app.modules.identity.models import IdentityMapping
            try:
                im = db.query(IdentityMapping).filter(IdentityMapping.id == uuid.UUID(str(path_params["mapping_id"]))).first()
                if im:
                    project_id = im.project_id
            except (TypeError, ValueError):
                pass

        caps, _, _ = get_user_context_capabilities(db, user, project_id=project_id, case_id=case_id)
        return capability in caps
