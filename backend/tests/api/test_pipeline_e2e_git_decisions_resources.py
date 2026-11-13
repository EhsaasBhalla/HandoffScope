"""End-to-end integration test for the full pipeline.

Validates:
1. Project creation.
2. Source connection and git commits ingestion.
3. Git history query endpoint (GitHub-style view and search).
4. Document upload and inline browser view (Content-Disposition: inline).
5. Handover case creation and initial reconstruction.
6. Decision regeneration across case-level and individual claim-level.
7. Question creation and AI draft generation.
8. Human response submission with attached resources (document and repository commit).
9. Response attachments verification and review approval workflow.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.db.base import SessionLocal
from app.db.enums import ProcessingStatus, Sensitivity, SourceRecordType
from app.main import app
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim
from app.modules.workspaces.models import User

client = TestClient(app)


def test_full_pipeline_git_history_decisions_and_attachments():
    # 1. Login as Maya (Tech Lead / Case Manager)
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Retrieve user and default workspace
    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    user_data = me_resp.json()
    user_id = uuid.UUID(user_data["id"])

    db = SessionLocal()
    from app.modules.workspaces.models import Workspace
    workspace = db.query(Workspace).first()
    assert workspace is not None
    workspace_id = workspace.id
    db.close()

    # 3. Create a new project
    proj_resp = client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        json={
            "name": f"E2E Integration Project {uuid.uuid4().hex[:6]}",
            "slug": f"e2e-project-{uuid.uuid4().hex[:6]}",
            "description": "Project for end-to-end testing of git history and decision flows",
            "auto_link_source": False,
        },
        headers=headers,
    )
    assert proj_resp.status_code == 201
    project_id = uuid.UUID(proj_resp.json()["id"])

    # 4. Connect a repository source and create commit records
    from app.db.enums import ConnectionStatus, SourceType
    db = SessionLocal()
    source = ConnectedSource(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=SourceType.GITHUB_REPO,
        name="org/e2e-service-repo",
        connection_status=ConnectionStatus.ACTIVE,
        config={"repo": "org/e2e-service-repo", "branch": "main"},
    )
    db.add(source)
    db.flush()

    commit_sha = "a1b2c3d4e5f678901234567890abcdef12345678"
    commit_record = SourceRecord(
        id=uuid.uuid4(),
        connected_source_id=source.id,
        source_type="GITHUB_REPO",
        record_type=SourceRecordType.COMMIT,
        external_id=commit_sha,
        title="feat: adopt distributed pubsub and partitioning for high throughput",
        body="Architectural decision to migrate from direct RPC to partitioned pubsub queues.",
        author_name="Maya Sharma",
        author_external_id="maya-sharma",
        author_mapped_user_id=user_id,
        url=f"https://github.com/org/e2e-service-repo/commit/{commit_sha}",
        state="merged",
        sensitivity=Sensitivity.GENERAL,
        processing_status=ProcessingStatus.COMPLETED,
        metadata_json={
            "sha": commit_sha,
            "commit": {
                "message": "feat: adopt distributed pubsub and partitioning for high throughput\n\nFull architecture description.",
                "author": {"name": "Maya Sharma", "email": "maya@example.test", "date": datetime.now(timezone.utc).isoformat()},
            },
        },
        external_created_at=datetime.now(timezone.utc),
    )
    db.add(commit_record)
    db.commit()
    commit_record_id = commit_record.id
    db.close()

    # 5. Verify Git history endpoint
    git_resp = client.get(
        f"/api/v1/projects/{project_id}/git-history",
        headers=headers,
    )
    assert git_resp.status_code == 200
    git_data = git_resp.json()
    assert git_data["total"] >= 1
    assert any(c["sha"] == commit_sha for c in git_data["items"])
    matching_commit = next(c for c in git_data["items"] if c["sha"] == commit_sha)
    assert matching_commit["short_sha"] == commit_sha[:7]
    assert "pubsub" in (matching_commit["message"] or matching_commit["title"]).lower()
    assert matching_commit["url"] == f"https://github.com/org/e2e-service-repo/commit/{commit_sha}"

    # Search filter in Git history
    search_resp = client.get(
        f"/api/v1/projects/{project_id}/git-history?search=pubsub",
        headers=headers,
    )
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] >= 1

    # 6. Upload a document and verify inline view
    doc_content = b"# Architecture Runbook\n\nDocumenting the decision to use partitioned event pubsub."
    file_tuple = ("runbook.md", io.BytesIO(doc_content), "text/markdown")
    doc_upload_resp = client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": file_tuple},
        headers=headers,
    )
    assert doc_upload_resp.status_code == 201
    doc_id = uuid.UUID(doc_upload_resp.json()["id"])

    # Test inline view endpoint
    view_resp = client.get(
        f"/api/v1/documents/{doc_id}/view",
        headers=headers,
    )
    assert view_resp.status_code == 200
    assert "inline" in view_resp.headers.get("content-disposition", "")
    assert b"Architecture Runbook" in view_resp.content

    # Also test download endpoint with inline=true
    download_inline_resp = client.get(
        f"/api/v1/documents/{doc_id}/download?inline=true",
        headers=headers,
    )
    assert download_inline_resp.status_code == 200
    assert "inline" in download_inline_resp.headers.get("content-disposition", "")

    # 7. Create a Handover Case for the project
    case_resp = client.post(
        f"/api/v1/projects/{project_id}/cases",
        json={
            "title": "Platform Handover Case",
            "description": "Transfer case for distributed pubsub pipeline",
            "transition_type": "INTERNAL_TRANSFER",
        },
        headers=headers,
    )
    assert case_resp.status_code == 201
    case_id = uuid.UUID(case_resp.json()["id"])

    # 8. Trigger reconstruction on the case
    recon_resp = client.post(
        f"/api/v1/cases/{case_id}/reconstruct",
        headers=headers,
    )
    assert recon_resp.status_code == 200
    recon_data = recon_resp.json()
    assert recon_data["status"] == "COMPLETED"
    assert recon_data["packs_created"] >= 1

    # 9. Test Decision Regeneration for the case
    regen_case_resp = client.post(
        f"/api/v1/cases/{case_id}/regenerate-decisions",
        headers=headers,
    )
    assert regen_case_resp.status_code == 200
    regen_data = regen_case_resp.json()
    assert regen_data["status"] == "COMPLETED"
    assert regen_data["total_decisions"] >= 1
    assert "message" in regen_data

    # 10. Test Single Decision Regeneration on an individual decision claim
    assert len(regen_data["claims"]) >= 1
    decision_claim = regen_data["claims"][0]
    decision_claim_id = decision_claim["id"]

    regen_single_resp = client.post(
        f"/api/v1/claims/{decision_claim_id}/regenerate-decision",
        headers=headers,
    )
    assert regen_single_resp.status_code == 200
    single_data = regen_single_resp.json()
    assert single_data["id"] == str(decision_claim_id)
    assert single_data["claim_type"] == "DECISION"
    assert single_data["freshness"] in ("CURRENT", "FRESH")
    assert "evidence" in single_data

    # 11. Create a Question on the case
    question_resp = client.post(
        f"/api/v1/cases/{case_id}/questions",
        json={
            "case_id": str(case_id),
            "question_text": "What is the rationale behind the pubsub partitioning model?",
            "why_it_matters": "Successors must operate and tune partition counts safely.",
            "priority": "HIGH",
        },
        headers=headers,
    )
    assert question_resp.status_code == 201
    question_id = uuid.UUID(question_resp.json()["id"])

    # 12. Generate AI Draft Answer
    ai_gen_resp = client.post(
        f"/api/v1/questions/{question_id}/generate-answer",
        headers=headers,
    )
    assert ai_gen_resp.status_code == 200
    ai_gen_data = ai_gen_resp.json()
    assert len(ai_gen_data["responses"]) >= 1
    draft_response = ai_gen_data["responses"][0]
    assert draft_response["is_ai_generated"] is True

    # 13. Submit Human Response with Attached Resources (Document + Git Commit)
    answer_resp = client.post(
        f"/api/v1/questions/{question_id}/responses",
        json={
            "response_text": "Partitioning ensures horizontal scaling and ordered event distribution per tenant.",
            "attachments": [
                {
                    "title": "runbook.md",
                    "type": "DOCUMENT",
                    "document_id": str(doc_id),
                    "url": f"/api/v1/documents/{doc_id}/view",
                },
                {
                    "title": "feat: adopt distributed pubsub and partitioning",
                    "type": "COMMIT",
                    "source_id": str(commit_record_id),
                    "url": f"https://github.com/org/e2e-service-repo/commit/{commit_sha}",
                },
            ],
            "evidence_references": [
                {
                    "source_id": str(commit_record_id),
                    "source_type": "COMMIT",
                    "title": "Commit a1b2c3d",
                    "url": f"https://github.com/org/e2e-service-repo/commit/{commit_sha}",
                }
            ],
        },
        headers=headers,
    )
    assert answer_resp.status_code == 200
    human_answer_data = answer_resp.json()
    assert human_answer_data["status"] == "ANSWERED"
    latest_response = human_answer_data["responses"][-1]
    assert latest_response["is_ai_generated"] is False
    assert len(latest_response["attachments"]) == 2

    # Verify attachment attributes
    doc_att = next(a for a in latest_response["attachments"] if a["type"] == "DOCUMENT")
    assert doc_att["document_id"] == str(doc_id)
    assert doc_att["url"] == f"/api/v1/documents/{doc_id}/view"

    commit_att = next(a for a in latest_response["attachments"] if a["type"] == "COMMIT")
    assert commit_att["source_id"] == str(commit_record_id)
    assert commit_sha in commit_att["url"]

    # 14. Review and Accept Question Response
    review_resp = client.patch(
        f"/api/v1/questions/{question_id}/review",
        json={
            "action": "accept",
            "notes": "Verified against runbook and commit architecture.",
        },
        headers=headers,
    )
    assert review_resp.status_code == 200
    review_data = review_resp.json()
    assert review_data["status"] == "RESOLVED"
    accepted_response = next(
        r for r in review_data["responses"] if not r["is_ai_generated"]
    )
    assert accepted_response["review_state"] == "ACCEPTED"
    assert accepted_response["review_notes"] == "Verified against runbook and commit architecture."
