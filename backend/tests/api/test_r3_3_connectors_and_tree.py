"""Tests for Phase R3-3: GitLab/Jira/Linear connectors, credential encryption, cross-tool identity, and GitHub tree indexer."""

from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.core.credentials import decrypt_secret, encrypt_secret
from app.db.enums import IdentityConfidence, SourceRecordType, SourceType
from app.db.session import SessionLocal
from app.integrations.connectors.base import ConnectorAuthError, ConnectorRateLimitError
from app.integrations.connectors.gitlab_connector import GitLabConnector
from app.integrations.connectors.jira_connector import JiraConnector, extract_adf_text
from app.integrations.connectors.linear_connector import LinearConnector
from app.integrations.github.client import GitHubClient
from app.integrations.github.tree_indexer import index_github_repo_tree
from app.main import app
from app.modules.identity.models import IdentityMapping
from app.modules.identity.service import auto_suggest_mappings
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource
from app.modules.workspaces.models import Workspace


def _login_as(client: TestClient, email: str) -> None:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "handoffscope-dev-2026"},
    )
    assert res.status_code == 200, res.text
    csrf_token = res.cookies.get("csrf_token") or res.json().get("csrf_token", "")
    client.headers.update({"X-CSRF-Token": csrf_token})


def test_connector_credential_encryption_and_api_masking():
    client = TestClient(app)
    _login_as(client, "maya.sharma@example.test")

    db = SessionLocal()
    try:
        ws = db.query(Workspace).first()
        proj = db.query(Project).filter(Project.workspace_id == ws.id).first()
        proj_id = proj.id
    finally:
        db.close()

    raw_secret_token = "lin_api_topsecretvalue1234567890"
    res = client.post(
        f"/api/v1/projects/{proj_id}/sources",
        json={
            "source_type": "LINEAR_TEAM",
            "name": "Linear Engineering",
            "external_id": "ENG",
            "config": {"team_key": "ENG", "access_token": raw_secret_token},
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert raw_secret_token not in res.text
    assert body["config"]["token_configured"] is True
    assert "access_token" not in body["config"]

    # Confirm DB stores encrypted enc:v1: ciphertext and round-trips cleanly
    db = SessionLocal()
    try:
        src = db.query(ConnectedSource).filter(ConnectedSource.id == uuid.UUID(body["id"])).first()
        stored_cipher = src.config["access_token"]
        assert stored_cipher.startswith("enc:v1:")
        assert stored_cipher != raw_secret_token
        assert decrypt_secret(stored_cipher) == raw_secret_token
        # Confirm encrypt helper idempotency
        assert encrypt_secret(stored_cipher) == stored_cipher
    finally:
        db.close()


def test_gitlab_linear_jira_connectors_with_mock_transport():
    # 1. GitLab paginated REST v4 + error handling
    def gitlab_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        page = request.url.params.get("page", "1")
        if "/merge_requests/" in path and path.endswith("/notes"):
            return httpx.Response(200, json=[
                {"id": 901, "body": "LGTM, ready to deploy", "author": {"username": "arjun.patel", "name": "Arjun Patel"}, "created_at": "2026-11-01T10:00:00Z", "system": False}
            ])
        if path.endswith("/merge_requests"):
            if page == "1":
                return httpx.Response(
                    200,
                    headers={"X-Next-Page": "2"},
                    json=[{
                        "iid": 11,
                        "title": "Add circuit breaker",
                        "description": "Prevents cascade timeouts",
                        "state": "merged",
                        "merged_at": "2026-11-01T11:00:00Z",
                        "created_at": "2026-11-01T09:00:00Z",
                        "updated_at": "2026-11-01T11:00:00Z",
                        "author": {"username": "arjun.patel", "name": "Arjun Patel"},
                        "labels": ["reliability"],
                        "web_url": "https://gitlab.com/org/app/-/merge_requests/11",
                    }],
                )
            return httpx.Response(200, json=[])
        if path.endswith("/issues"):
            return httpx.Response(200, json=[{
                "iid": 22,
                "title": "Retry queue backlog",
                "description": "Investigate dead-letter queue",
                "state": "opened",
                "created_at": "2026-11-02T08:00:00Z",
                "updated_at": "2026-11-02T09:00:00Z",
                "author": {"username": "renovate-bot[bot]", "name": "Renovate"},
                "web_url": "https://gitlab.com/org/app/-/issues/22",
            }])
        if path.endswith("/repository/commits"):
            return httpx.Response(200, json=[{
                "id": "abcdef123456",
                "short_id": "abcdef12",
                "title": "Tune pool timeout",
                "message": "Tune pool timeout to 5s",
                "author_name": "Arjun Patel",
                "author_email": "arjun.patel@example.test",
                "authored_date": "2026-11-03T10:00:00Z",
                "committed_date": "2026-11-03T10:00:00Z",
                "web_url": "https://gitlab.com/org/app/-/commit/abcdef123456",
            }])
        return httpx.Response(404)

    gl = GitLabConnector(project_path="org/app", transport=httpx.MockTransport(gitlab_handler))
    gl_res = gl.fetch_records()
    gl.close()
    assert len(gl_res.records) == 3
    assert any(r["record_type"] == SourceRecordType.PR and r["metadata_json"]["platform"] == "gitlab" for r in gl_res.records)
    assert ("PR", "gl-mr-11") in gl_res.events_by_key

    # 2. Linear GraphQL cursor pagination + GraphQL HTTP 200 error handling
    linear_calls = {"count": 0}

    def linear_handler(request: httpx.Request) -> httpx.Response:
        linear_calls["count"] += 1
        payload = json.loads(request.content.decode("utf-8"))
        after = (payload.get("variables") or {}).get("after")
        if after is None:
            return httpx.Response(200, json={
                "data": {
                    "issues": {
                        "nodes": [{
                            "id": "lin-1",
                            "identifier": "ENG-101",
                            "title": "Migrate webhook signer",
                            "description": "Use HMAC SHA-256",
                            "url": "https://linear.app/org/issue/ENG-101",
                            "priorityLabel": "High",
                            "createdAt": "2026-11-01T00:00:00Z",
                            "updatedAt": "2026-11-04T12:00:00Z",
                            "state": {"name": "In Progress", "type": "started"},
                            "team": {"id": "t1", "key": "ENG", "name": "Engineering"},
                            "project": {"id": "p1", "name": "Core"},
                            "assignee": {"id": "u1", "displayName": "Dev Mehta", "email": "dev.mehta@example.test"},
                            "creator": {"id": "u2", "displayName": "Maya Sharma", "email": "maya.sharma@example.test"},
                            "labels": {"nodes": [{"name": "security"}]},
                            "comments": {"nodes": [{"id": "c1", "body": "Verify constant-time compare", "createdAt": "2026-11-04T13:00:00Z", "user": {"displayName": "Maya Sharma"}}]},
                        }],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-2"},
                    }
                }
            })
        return httpx.Response(200, json={"data": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}})

    lin = LinearConnector(team_key="ENG", api_key="lin_api_test123", transport=httpx.MockTransport(linear_handler))
    lin_res = lin.fetch_records()
    lin.close()
    assert linear_calls["count"] == 2
    assert len(lin_res.records) == 1
    assert lin_res.records[0]["external_id"] == "ENG-101"
    assert ("ISSUE", "ENG-101") in lin_res.events_by_key

    # GraphQL HTTP 200 RATELIMITED error raised cleanly
    def linear_err_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Rate limit hit", "extensions": {"code": "RATELIMITED"}}]})

    lin_err = LinearConnector(team_key="ENG", api_key="lin_api_test123", transport=httpx.MockTransport(linear_err_handler))
    try:
        lin_err.fetch_records()
        raise AssertionError("Expected ConnectorRateLimitError")
    except ConnectorRateLimitError:
        pass
    finally:
        lin_err.close()

    # 3. Jira Cloud REST v3 `/rest/api/3/search/jql` + ADF text extraction + 401 check
    jira_paths: list[str] = []

    def jira_handler(request: httpx.Request) -> httpx.Response:
        jira_paths.append(request.url.path)
        assert request.url.path == "/rest/api/3/search/jql", "Must use active /search/jql endpoint!"
        return httpx.Response(200, json={
            "isLast": True,
            "issues": [{
                "key": "PLAT-42",
                "fields": {
                    "summary": "Rotate staging TLS certificate",
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Use certbot DNS-01 challenge."}]}],
                    },
                    "status": {"name": "In Review", "statusCategory": {"key": "indeterminate"}},
                    "issuetype": {"name": "Task"},
                    "priority": {"name": "High"},
                    "assignee": {"accountId": "acc-neha", "displayName": "Neha Gupta", "emailAddress": "neha.gupta@example.test"},
                    "reporter": {"accountId": "acc-maya", "displayName": "Maya Sharma"},
                    "created": "2026-11-01T08:00:00.000+0000",
                    "updated": "2026-11-05T09:00:00.000+0000",
                    "labels": ["infra"],
                    "comment": {"comments": []},
                },
            }],
        })

    jira = JiraConnector(
        site_url="https://acme.atlassian.net",
        project_key="PLAT",
        email="bot@acme.test",
        api_token="jira-tok",
        transport=httpx.MockTransport(jira_handler),
    )
    jira_res = jira.fetch_records()
    jira.close()
    assert jira_paths == ["/rest/api/3/search/jql"]
    assert len(jira_res.records) == 1
    assert "certbot DNS-01 challenge" in jira_res.records[0]["body"]
    assert extract_adf_text({"type": "text", "text": "Hello"}) == "Hello"


def test_cross_platform_identity_suggestions_never_auto_verify_and_skip_bots():
    db = SessionLocal()
    try:
        ws = db.query(Workspace).first()
        proj = Project(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            name="Cross Platform ID Test",
            slug=f"r3-id-{uuid.uuid4().hex[:6]}",
        )
        db.add(proj)
        db.flush()

        s_gl = ConnectedSource(id=uuid.uuid4(), project_id=proj.id, source_type=SourceType.GITLAB_REPO, name="gl/app")
        s_jr = ConnectedSource(id=uuid.uuid4(), project_id=proj.id, source_type=SourceType.JIRA_PROJECT, name="PLAT")
        db.add_all([s_gl, s_jr])
        db.flush()

        db.add_all([
            SourceRecord(
                id=uuid.uuid4(),
                connected_source_id=s_gl.id,
                source_type="GITLAB_REPO",
                record_type=SourceRecordType.COMMIT,
                external_id="sha1",
                title="Commit 1",
                author_external_id="dev_gitlab_handle",
                author_name="Dev",
                metadata_json={"author_email": "dev.mehta@example.test"},
            ),
            SourceRecord(
                id=uuid.uuid4(),
                connected_source_id=s_jr.id,
                source_type="JIRA_PROJECT",
                record_type=SourceRecordType.ISSUE,
                external_id="PLAT-1",
                title="Ticket 1",
                author_external_id="neha_jira_uid",
                author_name="Neha Gupta",
                metadata_json={"author_email": "neha.gupta@example.test"},
            ),
            SourceRecord(
                id=uuid.uuid4(),
                connected_source_id=s_gl.id,
                source_type="GITLAB_REPO",
                record_type=SourceRecordType.ISSUE,
                external_id="bot-issue",
                title="Bump deps",
                author_external_id="dependabot[bot]",
                author_name="Dependabot",
            ),
        ])
        db.commit()

        mappings = auto_suggest_mappings(db, proj.id)
        by_user = {m.external_username: m for m in mappings}
        assert "dependabot[bot]" not in by_user
        assert by_user["dev_gitlab_handle"].external_provider == "gitlab"
        assert by_user["dev_gitlab_handle"].confidence == IdentityConfidence.SUGGESTED
        assert by_user["neha_jira_uid"].external_provider == "jira"
        assert by_user["neha_jira_uid"].confidence == IdentityConfidence.SUGGESTED
        # Verified DB check: no mapping was auto-promoted to VERIFIED
        assert db.query(IdentityMapping).filter(
            IdentityMapping.project_id == proj.id,
            IdentityMapping.confidence == IdentityConfidence.VERIFIED,
        ).count() == 0
    finally:
        db.close()


def test_github_repo_tree_indexer_excludes_secrets_binaries_and_deduplicates_blobs():
    db = SessionLocal()
    try:
        ws = db.query(Workspace).first()
        proj = db.query(Project).first()
        src = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="org/demo-tree",
            external_id="org/demo-tree",
        )
        db.add(src)
        db.commit()
        src_id = src.id

        readme_b64 = base64.b64encode(b"# Service Overview\nJWT_SECRET_KEY=supersecretproductionvalue99\n").decode("ascii")
        auth_b64 = base64.b64encode(b"def verify():\n    return True\n").decode("ascii")

        gh = GitHubClient()
        blob_calls: list[str] = []

        with patch.object(gh, "get_repo", return_value={"default_branch": "main"}), \
             patch.object(gh, "get_branch", return_value={"commit": {"sha": "commit-1", "commit": {"tree": {"sha": "tree-1"}, "committer": {"date": "2026-11-10T12:00:00Z"}}}}), \
             patch.object(gh, "get_git_tree", return_value={
                 "truncated": False,
                 "tree": [
                     {"path": "README.md", "mode": "100644", "type": "blob", "sha": "blob-readme-1", "size": 120},
                     {"path": "src/auth.py", "mode": "100644", "type": "blob", "sha": "blob-auth-1", "size": 90},
                     {"path": ".env.production", "mode": "100644", "type": "blob", "sha": "blob-env", "size": 80},
                     {"path": "certs/prod.pem", "mode": "100644", "type": "blob", "sha": "blob-pem", "size": 200},
                     {"path": "assets/logo.png", "mode": "100644", "type": "blob", "sha": "blob-png", "size": 500},
                     {"path": "node_modules/pkg/index.js", "mode": "100644", "type": "blob", "sha": "blob-nm", "size": 100},
                     {"path": "evil-symlink", "mode": "120000", "type": "blob", "sha": "blob-sym", "size": 40},
                 ],
             }), \
             patch.object(gh, "get_git_blob", side_effect=lambda o, r, sha: (blob_calls.append(sha) or {"encoding": "base64", "content": readme_b64 if sha == "blob-readme-1" else auth_b64})):
            res1 = index_github_repo_tree(db, client=gh, source_id=src_id, owner="org", repo="demo-tree")
            db.commit()

            assert res1["files_created"] == 2
            assert set(blob_calls) == {"blob-readme-1", "blob-auth-1"}

            recs = db.query(SourceRecord).filter(SourceRecord.connected_source_id == src_id).all()
            ext_ids = {r.external_id for r in recs}
            assert ext_ids == {"repo-file:README.md", "repo-file:src/auth.py"}
            readme_rec = next(r for r in recs if r.external_id == "repo-file:README.md")
            # Secret inside README must be masked before storage!
            assert "supersecretproductionvalue99" not in (readme_rec.body or "")
            assert "[REDACTED:SECRET]" in (readme_rec.body or "")

            # Second sync with identical SHAs should download ZERO blobs and remove src/auth.py if removed from tree
            blob_calls.clear()
            with patch.object(gh, "get_git_tree", return_value={
                "truncated": False,
                "tree": [{"path": "README.md", "mode": "100644", "type": "blob", "sha": "blob-readme-1", "size": 120}],
            }):
                res2 = index_github_repo_tree(db, client=gh, source_id=src_id, owner="org", repo="demo-tree")
                db.commit()
                assert blob_calls == []
                assert res2["files_unchanged"] == 1
                assert res2["files_deleted"] == 1
    finally:
        db.close()
