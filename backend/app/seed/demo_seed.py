"""Demo seed data — 7 users, 1 workspace, 1 project, all memberships + fixture.

Run: python -m app.seed.demo_seed
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import SessionLocal
from app.db.enums import ProjectRole, WorkspaceRole
from app.modules.projects.models import Project, ProjectMembership
from app.modules.workspaces.models import User, Workspace, WorkspaceMembership

logger = logging.getLogger("handoffscope.seed")

# ── Demo Users ────────────────────────────────────────────────
DEMO_USERS = [
    {
        "email": "maya.sharma@example.test",
        "display_name": "Maya Sharma",
        "ws_role": WorkspaceRole.OWNER,
        "proj_role": ProjectRole.LEAD,
    },
    {
        "email": "arjun.patel@example.test",
        "display_name": "Arjun Patel",
        "ws_role": WorkspaceRole.ADMIN,
        "proj_role": ProjectRole.CONTRIBUTOR,
    },
    {
        "email": "neha.gupta@example.test",
        "display_name": "Neha Gupta",
        "ws_role": WorkspaceRole.MEMBER,
        "proj_role": ProjectRole.CONTRIBUTOR,
    },
    {
        "email": "kabir.singh@example.test",
        "display_name": "Kabir Singh",
        "ws_role": WorkspaceRole.MEMBER,
        "proj_role": ProjectRole.CONTRIBUTOR,
    },
    {
        "email": "aisha.khan@example.test",
        "display_name": "Aisha Khan",
        "ws_role": WorkspaceRole.MEMBER,
        "proj_role": ProjectRole.REVIEWER,
    },
    {
        "email": "dev.mehta@example.test",
        "display_name": "Dev Mehta",
        "ws_role": WorkspaceRole.MEMBER,
        "proj_role": ProjectRole.CONTRIBUTOR,
    },
    {
        "email": "priya.nair@example.test",
        "display_name": "Priya Nair",
        "ws_role": WorkspaceRole.MEMBER,
        "proj_role": ProjectRole.CONTRIBUTOR,
    },
]


def seed_demo_data(db: Session) -> None:
    """Create all demo data idempotently."""
    password_hash = hash_password(settings.DEMO_USER_PASSWORD)

    # ── Create users ──────────────────────────────────────────
    users: dict[str, User] = {}
    for u_data in DEMO_USERS:
        user = db.query(User).filter(User.email == u_data["email"]).first()
        if not user:
            user = User(
                email=u_data["email"],
                display_name=u_data["display_name"],
                password_hash=password_hash,
                is_active=True,
            )
            db.add(user)
            db.flush()
            logger.info("Created user: %s", user.email)
        else:
            logger.info("User already exists: %s", user.email)
        users[u_data["email"]] = user

    # ── Create workspace ──────────────────────────────────────
    workspace = db.query(Workspace).filter(Workspace.slug == "acme-engineering").first()
    if not workspace:
        workspace = Workspace(
            name="Acme Engineering",
            slug="acme-engineering",
            description="Primary engineering workspace for HandoffScope demo",
        )
        db.add(workspace)
        db.flush()
        logger.info("Created workspace: %s", workspace.slug)
    else:
        logger.info("Workspace already exists: %s", workspace.slug)

    # ── Create workspace memberships ──────────────────────────
    for u_data in DEMO_USERS:
        user = users[u_data["email"]]
        existing = (
            db.query(WorkspaceMembership)
            .filter(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.workspace_id == workspace.id,
            )
            .first()
        )
        if not existing:
            membership = WorkspaceMembership(
                user_id=user.id,
                workspace_id=workspace.id,
                role=u_data["ws_role"],
            )
            db.add(membership)
            logger.info("Added %s to workspace as %s", user.email, u_data["ws_role"].value)

    db.flush()

    # ── Create project ────────────────────────────────────────
    project = db.query(Project).filter(Project.slug == "atlas-platform").first()
    if not project:
        project = Project(
            workspace_id=workspace.id,
            name="Atlas Platform",
            slug="atlas-platform",
            description="Core platform service — the primary handover target for the demo scenario",
            repo_url="https://github.com/acme-eng/atlas-platform",
        )
        db.add(project)
        db.flush()
        logger.info("Created project: %s", project.slug)
    else:
        logger.info("Project already exists: %s", project.slug)

    # ── Create project memberships ────────────────────────────
    for u_data in DEMO_USERS:
        user = users[u_data["email"]]
        existing = (
            db.query(ProjectMembership)
            .filter(
                ProjectMembership.user_id == user.id,
                ProjectMembership.project_id == project.id,
            )
            .first()
        )
        if not existing:
            pm = ProjectMembership(
                user_id=user.id,
                project_id=project.id,
                role=u_data["proj_role"],
            )
            db.add(pm)
            logger.info("Added %s to project as %s", user.email, u_data["proj_role"].value)

    # ── Create Pydantic testing project & source ──────────────
    pydantic_proj = db.query(Project).filter(Project.slug == "pydantic").first()
    if not pydantic_proj:
        pydantic_proj = Project(
            workspace_id=workspace.id,
            name="Pydantic",
            slug="pydantic",
            description="Data validation using Python type hints",
            repo_url="https://github.com/pydantic/pydantic",
        )
        db.add(pydantic_proj)
        db.flush()
        logger.info("Created project: %s", pydantic_proj.slug)

    for u_data in DEMO_USERS:
        user = users[u_data["email"]]
        existing = (
            db.query(ProjectMembership)
            .filter(
                ProjectMembership.user_id == user.id,
                ProjectMembership.project_id == pydantic_proj.id,
            )
            .first()
        )
        if not existing:
            db.add(ProjectMembership(user_id=user.id, project_id=pydantic_proj.id, role=u_data["proj_role"]))

    from app.modules.sources.models import ConnectedSource
    from app.db.enums import SourceType, ConnectionStatus
    pyd_source = db.query(ConnectedSource).filter(
        ConnectedSource.project_id == pydantic_proj.id,
        ConnectedSource.name == "pydantic/pydantic",
    ).first()
    if not pyd_source:
        pyd_source = ConnectedSource(
            project_id=pydantic_proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="pydantic/pydantic",
            external_id="pydantic/pydantic",
            connection_status=ConnectionStatus.ACTIVE,
            config={"owner": "pydantic", "repo": "pydantic"},
            connected_by_id=users["maya.sharma@example.test"].id,
        )
        db.add(pyd_source)
        logger.info("Connected pydantic/pydantic source to Pydantic project")

    # ── Create Zulip testing project & source ─────────────────
    zulip_proj = db.query(Project).filter(Project.slug == "zulip").first()
    if not zulip_proj:
        zulip_proj = Project(
            workspace_id=workspace.id,
            name="Zulip",
            slug="zulip",
            description="Zulip server and web application. Open-source team chat that helps teams stay productive and focused.",
            repo_url="https://github.com/zulip/zulip",
        )
        db.add(zulip_proj)
        db.flush()
        logger.info("Created project: %s", zulip_proj.slug)

    for u_data in DEMO_USERS:
        user = users[u_data["email"]]
        existing = (
            db.query(ProjectMembership)
            .filter(
                ProjectMembership.user_id == user.id,
                ProjectMembership.project_id == zulip_proj.id,
            )
            .first()
        )
        if not existing:
            db.add(ProjectMembership(user_id=user.id, project_id=zulip_proj.id, role=u_data["proj_role"]))

    zulip_source = db.query(ConnectedSource).filter(
        ConnectedSource.project_id == zulip_proj.id,
        ConnectedSource.name == "zulip/zulip",
    ).first()
    if not zulip_source:
        zulip_source = ConnectedSource(
            project_id=zulip_proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="zulip/zulip",
            external_id="zulip/zulip",
            connection_status=ConnectionStatus.ACTIVE,
            config={"owner": "zulip", "repo": "zulip"},
            connected_by_id=users["maya.sharma@example.test"].id,
        )
        db.add(zulip_source)
        logger.info("Connected zulip/zulip source to Zulip project")

    db.commit()
    logger.info("Demo seed complete — %d users, 1 workspace, 3 projects", len(DEMO_USERS))

    # ── Seed synthetic fixture (Phase 4) ──────────────────────
    from app.seed.demo_data import seed_synthetic_fixture
    seed_synthetic_fixture(db)


def main() -> None:
    """Entry point for running seed from command line."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
