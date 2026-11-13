"""Tests for Phase R3-0 foundations: project repo auto-source, member management RBAC, and shared clearance policy."""

from __future__ import annotations

import uuid
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ProcessingStatus,
    ProjectRole,
    Sensitivity,
    SourceRecordType,
    SourceType,
    TransitionType,
)
from app.db.session import SessionLocal
from app.main import app
from app.modules.audit.models import AuditEvent
from app.modules.evidence.clearance import has_restricted_clearance, resolve_case_source_ids
from app.modules.handover_cases.models import CaseParticipant, CaseSource, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource
from app.modules.sources.url_parser import parse_github_repo_identifier
from app.modules.workspaces.models import User, Workspace


def _login_as(client: TestClient, email: str) -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "handoffscope-dev-2026"},
    )
    assert res.status_code == 200, res.text
    csrf_token = res.cookies.get("csrf_token") or res.json().get("csrf_token", "")
    client.headers.update({"X-CSRF-Token": csrf_token})
    return res.json()["access_token"]


def test_github_url_parser_normalization():
    assert parse_github_repo_identifier("https://github.com/tiangolo/fastapi.git") == (
        "tiangolo",
        "fastapi",
        "https://github.com/tiangolo/fastapi",
    )
    assert parse_github_repo_identifier("git@github.com:pydantic/pydantic.git") == (
        "pydantic",
        "pydantic",
        "https://github.com/pydantic/pydantic",
    )
    assert parse_github_repo_identifier("zulip/zulip") == (
        "zulip",
        "zulip",
        "https://github.com/zulip/zulip",
    )
    assert parse_github_repo_identifier("   ") is None
    for bad in ["https://gitlab.com/org/repo", "invalid-slug", "github.com/onlyowner"]:
        try:
            parse_github_repo_identifier(bad)
            raise AssertionError(f"Expected ValueError for {bad}")
        except ValueError:
            pass


def test_project_creation_auto_links_github_source_and_validates_urls():
    client = TestClient(app)
    _login_as(client, "maya.sharma@example.test")

    db = SessionLocal()
    try:
        ws = db.query(Workspace).first()
        ws_id = ws.id
    finally:
        db.close()

    slug_with_repo = f"r3-auto-src-{uuid.uuid4().hex[:6]}"
    res = client.post(
        f"/api/v1/workspaces/{ws_id}/projects",
        json={
            "name": "R3 Auto Source Project",
            "slug": slug_with_repo,
            "repo_url": "https://github.com/pallets/flask.git",
        },
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["repo_url"] == "https://github.com/pallets/flask"
    assert payload["connected_source_id"] is not None
    assert payload["linked_source_status"] == "ACTIVE"

    sources = client.get(f"/api/v1/projects/{payload['id']}/sources").json()
    assert any(
        s["id"] == payload["connected_source_id"]
        and s["source_type"] == "GITHUB_REPO"
        and s["external_id"] == "pallets/flask"
        for s in sources
    )

    # No-repo project still creates without connected_source_id
    slug_no_repo = f"r3-no-repo-{uuid.uuid4().hex[:6]}"
    res_plain = client.post(
        f"/api/v1/workspaces/{ws_id}/projects",
        json={"name": "No Repo Project", "slug": slug_no_repo},
    )
    assert res_plain.status_code == 201, res_plain.text
    assert res_plain.json()["connected_source_id"] is None

    # Invalid URL rejects cleanly without orphan project
    bad_slug = f"r3-bad-url-{uuid.uuid4().hex[:6]}"
    res_bad = client.post(
        f"/api/v1/workspaces/{ws_id}/projects",
        json={
            "name": "Bad Repo",
            "slug": bad_slug,
            "repo_url": "https://notgithub.example.com/org/repo",
        },
    )
    assert res_bad.status_code == 400
    db = SessionLocal()
    try:
        assert db.query(Project).filter(Project.slug == bad_slug).first() is None
    finally:
        db.close()


def test_project_member_management_permissions_and_last_lead_protection():
    client = TestClient(app)
    _login_as(client, "maya.sharma@example.test")

    db = SessionLocal()
    try:
        ws = db.query(Workspace).first()
        ws_id = ws.id
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        neha = db.query(User).filter(User.email == "neha.gupta@example.test").first()
        outsider = User(
            id=uuid.uuid4(),
            email=f"outsider-{uuid.uuid4().hex[:6]}@example.test",
            display_name="Outside User",
            password_hash=hash_password("handoffscope-dev-2026"),
            is_active=True,
        )
        db.add(outsider)
        db.commit()
        maya_id, neha_id, outsider_id = maya.id, neha.id, outsider.id
    finally:
        db.close()

    proj = client.post(
        f"/api/v1/workspaces/{ws_id}/projects",
        json={"name": "Members RBAC Project", "slug": f"r3-members-{uuid.uuid4().hex[:6]}"},
    ).json()
    proj_id = proj["id"]

    # Last-lead downgrade & removal rejected with 409
    res_downgrade = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"user_id": str(maya_id), "role": "REVIEWER"},
    )
    assert res_downgrade.status_code == 409

    res_remove_last = client.delete(f"/api/v1/projects/{proj_id}/members/{maya_id}")
    assert res_remove_last.status_code == 409

    # Outside user rejected with 400
    res_outsider = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"user_id": str(outsider_id), "role": "CONTRIBUTOR"},
    )
    assert res_outsider.status_code == 400

    # Add Neha (workspace member) as REVIEWER, then update to CONTRIBUTOR
    res_add = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"user_id": str(neha_id), "role": "REVIEWER"},
    )
    assert res_add.status_code == 201
    assert res_add.json()["role"] == "REVIEWER"

    res_upd = client.post(
        f"/api/v1/projects/{proj_id}/members",
        json={"user_id": str(neha_id), "role": "CONTRIBUTOR"},
    )
    assert res_upd.status_code == 201
    assert res_upd.json()["role"] == "CONTRIBUTOR"

    # Unauthorized contributor cannot manage members
    _login_as(client, "neha.gupta@example.test")
    res_unauth = client.delete(f"/api/v1/projects/{proj_id}/members/{neha_id}")
    assert res_unauth.status_code == 403

    # Lead removes Neha and audit events are recorded
    _login_as(client, "maya.sharma@example.test")
    res_del = client.delete(f"/api/v1/projects/{proj_id}/members/{neha_id}")
    assert res_del.status_code == 204

    db = SessionLocal()
    try:
        actions = {
            e.action
            for e in db.query(AuditEvent)
            .filter(AuditEvent.action.in_(["project.member_added", "project.member_role_updated", "project.member_removed"]))
            .all()
        }
        assert {"project.member_added", "project.member_role_updated", "project.member_removed"} <= actions
    finally:
        db.close()


def test_shared_clearance_and_case_source_scope_across_routes():
    db = SessionLocal()
    try:
        ws = db.query(Workspace).first()
        maya = db.query(User).filter(User.email == "maya.sharma@example.test").first()
        aisha = db.query(User).filter(User.email == "aisha.khan@example.test").first()
        proj = Project(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            name="Clearance Test Proj",
            slug=f"r3-clr-{uuid.uuid4().hex[:6]}",
        )
        db.add(proj)
        db.flush()

        s_included = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            name="Included Source",
        )
        s_excluded = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            name="Excluded Source",
        )
        db.add_all([s_included, s_excluded])
        db.flush()

        rec_restricted = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=s_included.id,
            source_type="SYNTHETIC_FIXTURE",
            record_type=SourceRecordType.DOCUMENT_SECTION,
            external_id="secret-doc-1",
            title="Vault Token Spec",
            body="Secret internals",
            sensitivity=Sensitivity.RESTRICTED,
            processing_status=ProcessingStatus.COMPLETED,
        )
        rec_other = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=s_excluded.id,
            source_type="SYNTHETIC_FIXTURE",
            record_type=SourceRecordType.ISSUE,
            external_id="other-1",
            title="Out of scope record",
            body="Unscoped",
            sensitivity=Sensitivity.GENERAL,
            processing_status=ProcessingStatus.COMPLETED,
        )
        db.add_all([rec_restricted, rec_other])
        db.flush()

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=1,
            title="Scoped Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.DRAFT,
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()

        db.add(CaseSource(case_id=case.id, connected_source_id=s_included.id))
        db.add(
            CaseParticipant(
                case_id=case.id,
                user_id=aisha.id,
                role=CaseParticipantRole.RECIPIENT,
            )
        )
        db.commit()

        assert resolve_case_source_ids(db, case_id=case.id, project_id=proj.id) == [s_included.id]
        assert has_restricted_clearance(db, user_id=maya.id, project_id=proj.id, case_id=case.id, user=maya) is True
        assert has_restricted_clearance(db, user_id=aisha.id, project_id=proj.id, case_id=case.id, user=aisha) is False
        case_id, rec_restr_id, rec_other_id = case.id, rec_restricted.id, rec_other.id
    finally:
        db.close()

    client = TestClient(app)
    _login_as(client, "aisha.khan@example.test")
    assert client.get(f"/api/v1/cases/{case_id}/sources/records/{rec_restr_id}").status_code == 403
    assert client.get(f"/api/v1/cases/{case_id}/sources/records/{rec_other_id}").status_code == 404
    _login_as(client, "maya.sharma@example.test")
    assert client.get(f"/api/v1/cases/{case_id}/sources/records/{rec_restr_id}").status_code == 200
