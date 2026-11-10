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
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Extract the authenticated user from the JWT cookie.

    Returns the User ORM instance or raises 401.
    """
    # Import here to avoid circular dependency at module load time
    from app.modules.workspaces.models import User

    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — no access token cookie",
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
        "case.view", "case.create",
        "audit.view",
    },
    "ADMIN": {
        "workspace.view", "workspace.members.manage",
        "project.create", "project.view", "project.manage", "project.members.manage",
        "case.view", "case.create",
        "audit.view",
    },
    "MEMBER": {
        "workspace.view",
        "project.view",
        "case.view",
    },
}

# Capabilities granted to each project role
_PROJ_CAPABILITIES: dict[str, set[str]] = {
    "LEAD": {
        "project.view", "project.manage", "project.members.manage",
        "case.create", "case.view", "case.manage", "case.participants.manage",
        "source.connect", "source.view", "source.import",
        "extraction.trigger", "extraction.view",
        "pack.create", "pack.view", "pack.manage",
        "review.request", "review.view",
        "share.manage", "share.view",
        "identity.manage", "identity.view",
        "document.upload", "document.view",
        "audit.view",
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
    },
    "REVIEWER": {
        "project.view",
        "case.view",
        "source.view",
        "extraction.view",
        "pack.view",
        "review.submit", "review.view",
        "share.view",
        "identity.view",
        "document.view",
        "question.create", "question.view",
    },
}

# Capabilities granted to each case participation role
_CASE_CAPABILITIES: dict[str, set[str]] = {
    "INITIATOR": {
        "case.manage", "case.participants.manage",
        "source.connect", "source.import",
        "extraction.trigger",
        "pack.create", "pack.manage",
        "review.request",
        "share.manage",
    },
    "DEPARTING": {
        "case.view",
        "source.view",
        "extraction.view",
        "pack.view",
        "question.answer",
    },
    "REVIEWER": {
        "case.view",
        "review.submit",
        "question.create",
        "pack.view",
        "extraction.view",
    },
    "RECIPIENT": {
        "case.view",
        "pack.view",
        "question.create", "question.view",
        "acceptance.manage",
    },
    "CONTRIBUTOR": {
        "case.view",
        "source.view",
        "pack.view",
    },
    "AUDITOR": {
        "case.view",
        "audit.view",
        "pack.view",
        "review.view",
        "extraction.view",
    },
}


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
        """Evaluate permission using the full RBAC matrix.

        Evaluation order:
        1. Workspace role grants
        2. Project role grants (if project context available)
        3. Case participation grants (if case context available)
        """
        from app.modules.workspaces.models import WorkspaceMembership
        from app.modules.projects.models import ProjectMembership
        from app.modules.handover_cases.models import CaseParticipant, HandoverCase

        # ── 1. Workspace-level check ─────────────────────────────
        ws_memberships = db.query(WorkspaceMembership).filter(
            WorkspaceMembership.user_id == user.id
        ).all()
        for wm in ws_memberships:
            ws_caps = _WS_CAPABILITIES.get(wm.role.value, set())
            if capability in ws_caps:
                return True

        # ── 2. Project-level check ───────────────────────────────
        project_id = path_params.get("project_id")
        if project_id:
            try:
                project_id = uuid.UUID(str(project_id))
            except (TypeError, ValueError):
                project_id = None

        if project_id:
            pm = db.query(ProjectMembership).filter(
                ProjectMembership.user_id == user.id,
                ProjectMembership.project_id == project_id,
            ).first()
            if pm:
                proj_caps = _PROJ_CAPABILITIES.get(pm.role.value, set())
                if capability in proj_caps:
                    return True

        # ── 3. Case-level check ──────────────────────────────────
        case_id = path_params.get("case_id")
        if case_id:
            try:
                case_id = uuid.UUID(str(case_id))
            except (TypeError, ValueError):
                case_id = None

        if case_id:
            participants = db.query(CaseParticipant).filter(
                CaseParticipant.user_id == user.id,
                CaseParticipant.case_id == case_id,
            ).all()
            for cp in participants:
                case_caps = _CASE_CAPABILITIES.get(cp.role.value, set())
                if capability in case_caps:
                    return True

            # Also check project-level via the case's project
            case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
            if case:
                pm = db.query(ProjectMembership).filter(
                    ProjectMembership.user_id == user.id,
                    ProjectMembership.project_id == case.project_id,
                ).first()
                if pm:
                    proj_caps = _PROJ_CAPABILITIES.get(pm.role.value, set())
                    if capability in proj_caps:
                        return True

        # If no project/case context, check all user's project memberships
        if not project_id and not case_id:
            all_pm = db.query(ProjectMembership).filter(
                ProjectMembership.user_id == user.id
            ).all()
            for pm in all_pm:
                proj_caps = _PROJ_CAPABILITIES.get(pm.role.value, set())
                if capability in proj_caps:
                    return True

        return False
