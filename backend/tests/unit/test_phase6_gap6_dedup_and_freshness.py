"""Phase 6 (Gap 6) tests: safe GitHub deduplication, re-linking, CLI, sync telemetry, and local freshness."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.enums import (
    CaseStatus,
    ClaimType,
    ConnectionStatus,
    EvidenceState,
    JobStatus,
    JobType,
    ProjectRole,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
    TransitionType,
)
from app.db.session import SessionLocal
from app.modules.audit.models import AuditEvent
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import HandoverCase
from app.modules.ingestion.models import SourceEvent, SourceRecord
from app.modules.jobs.models import Job
from app.modules.projects.models import Project, ProjectMembership
from app.modules.sources.models import ConnectedSource
from app.modules.sources.service import cleanup_duplicate_github_records, refresh_source
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User


client = TestClient(app)


def test_github_sync_skips_pr_duplicates_and_reports_sync_telemetry(monkeypatch):
    session = SessionLocal()
    try:
        maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        seed_proj = session.query(Project).filter(Project.slug == "atlas-platform").first()
        assert maya and seed_proj

        proj = Project(
            id=uuid.uuid4(),
            workspace_id=seed_proj.workspace_id,
            name="Gap 6 Sync Telemetry Project",
            slug=f"gap6-sync-{uuid.uuid4().hex[:8]}",
        )
        session.add(proj)
        session.flush()
        session.add(ProjectMembership(project_id=proj.id, user_id=maya.id, role=ProjectRole.LEAD))

        src = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="acme/telemetry",
            external_id="acme/telemetry",
            connection_status=ConnectionStatus.ACTIVE,
            config={"owner": "acme", "repo": "telemetry", "access_token": "dummy-gh"},
            connected_by_id=maya.id,
        )
        session.add(src)
        session.flush()

        job = Job(
            id=uuid.uuid4(),
            job_type=JobType.SOURCE_IMPORT,
            status=JobStatus.PENDING,
            entity_type="connected_source",
            entity_id=src.id,
            created_by_id=maya.id,
            params={"source_id": str(src.id)},
            idempotency_key=f"test-sync-{uuid.uuid4().hex[:8]}",
        )
        session.add(job)
        session.commit()

        from app.integrations.github.client import GitHubClient
        from app.workers.import_task import run_import

        # Mock /issues returning BOTH a pure issue (#11) and a PR-shaped item (#42)
        monkeypatch.setattr(
            GitHubClient,
            "list_issues",
            lambda self, owner, repo: [
                {
                    "number": 11,
                    "title": "Fix connection pool leak",
                    "body": "Pool leak reported in staging",
                    "state": "open",
                    "html_url": "https://github.com/acme/telemetry/issues/11",
                    "user": {"login": "arjun"},
                    "labels": [],
                    "assignees": [],
                    "created_at": "2026-10-01T10:00:00Z",
                    "updated_at": "2026-10-02T10:00:00Z",
                },
                {
                    "number": 42,
                    "title": "Harden retry backoff",
                    "body": "PR #42 body",
                    "state": "closed",
                    "html_url": "https://github.com/acme/telemetry/pull/42",
                    "pull_request": {"url": "https://api.github.com/repos/acme/telemetry/pulls/42"},
                    "user": {"login": "arjun"},
                    "labels": [],
                    "assignees": [],
                    "created_at": "2026-10-03T10:00:00Z",
                    "updated_at": "2026-10-04T10:00:00Z",
                },
            ],
        )
        monkeypatch.setattr(
            GitHubClient,
            "list_pulls",
            lambda self, owner, repo: [
                {
                    "number": 42,
                    "title": "Harden retry backoff",
                    "body": "Canonical PR #42 body",
                    "state": "closed",
                    "merged_at": "2026-10-04T11:00:00Z",
                    "html_url": "https://github.com/acme/telemetry/pull/42",
                    "user": {"login": "arjun"},
                    "labels": [],
                    "assignees": [],
                    "created_at": "2026-10-03T10:00:00Z",
                    "updated_at": "2026-10-04T11:00:00Z",
                }
            ],
        )
        monkeypatch.setattr(GitHubClient, "list_issue_comments", lambda self, owner, repo, n: [])
        monkeypatch.setattr(GitHubClient, "list_pull_reviews", lambda self, owner, repo, n: [])
        monkeypatch.setattr(GitHubClient, "list_pull_review_comments", lambda self, owner, repo, n: [])
        monkeypatch.setattr(GitHubClient, "list_commits", lambda self, owner, repo: [])

        run_import(str(job.id))

        session.expire_all()
        recs = session.query(SourceRecord).filter(SourceRecord.connected_source_id == src.id).all()
        assert len(recs) == 2
        assert sum(1 for r in recs if r.record_type == SourceRecordType.PR and r.external_id == "42") == 1
        assert sum(1 for r in recs if r.record_type == SourceRecordType.ISSUE and r.external_id == "42") == 0
        assert sum(1 for r in recs if r.record_type == SourceRecordType.ISSUE and r.external_id == "11") == 1

        # Verify GET /projects/{id}/sources returns sync telemetry + skipped count
        client.post("/api/v1/auth/login", json={"email": "maya.sharma@example.test", "password": "handoffscope-dev-2026"})
        res = client.get(f"/api/v1/projects/{proj.id}/sources")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 1
        assert items[0]["last_successful_sync_at"] is not None
        last_run = items[0]["last_sync_run"]
        assert last_run["status"] == "COMPLETED"
        assert last_run["records_created"] == 2
        assert last_run["records_skipped"] == 1  # Filtered PR #42 from /issues
    finally:
        session.close()


def test_safe_dedup_relinking_ambiguous_preservation_rbac_idempotency_and_local_freshness(monkeypatch):
    session = SessionLocal()
    try:
        maya = session.query(User).filter(User.email == "maya.sharma@example.test").first()
        kabir = session.query(User).filter(User.email == "kabir.singh@example.test").first()
        aisha = session.query(User).filter(User.email == "aisha.khan@example.test").first()
        seed_proj = session.query(Project).filter(Project.slug == "atlas-platform").first()
        assert maya and kabir and aisha and seed_proj

        proj = Project(
            id=uuid.uuid4(),
            workspace_id=seed_proj.workspace_id,
            name="Gap 6 Dedup Project",
            slug=f"gap6-dedup-{uuid.uuid4().hex[:8]}",
        )
        session.add(proj)
        session.flush()
        session.add_all([
            ProjectMembership(project_id=proj.id, user_id=maya.id, role=ProjectRole.LEAD),
            ProjectMembership(project_id=proj.id, user_id=kabir.id, role=ProjectRole.REVIEWER),
            ProjectMembership(project_id=proj.id, user_id=aisha.id, role=ProjectRole.CONTRIBUTOR),
        ])

        src_a = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="acme/repo-a",
            external_id="acme/repo-a",
            connection_status=ConnectionStatus.ACTIVE,
            connected_by_id=maya.id,
        )
        src_b = ConnectedSource(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type=SourceType.GITHUB_REPO,
            name="acme/repo-b",
            external_id="acme/repo-b",
            connection_status=ConnectionStatus.ACTIVE,
            connected_by_id=maya.id,
        )
        session.add_all([src_a, src_b])
        session.flush()

        # Canonical PR #42 and duplicate PR-as-ISSUE #42 in src_a
        pr_42 = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src_a.id,
            source_type=SourceType.GITHUB_REPO,
            record_type=SourceRecordType.PR,
            external_id="42",
            title="Upgrade TLS cipher list",
            body="Canonical PR body",
            url="https://github.com/acme/repo-a/pull/42",
            metadata_json={"is_pull_request": True},
            external_updated_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
        )
        dup_issue_42 = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src_a.id,
            source_type=SourceType.GITHUB_REPO,
            record_type=SourceRecordType.ISSUE,
            external_id="42",
            title="Upgrade TLS cipher list",
            body="Duplicate issue payload",
            url="https://github.com/acme/repo-a/pull/42",
            metadata_json={"is_pull_request": True},
        )
        # Ambiguous pair #99 (ISSUE lacks PR URL and is_pull_request=True) -> MUST be skipped!
        amb_pr_99 = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src_a.id,
            source_type=SourceType.GITHUB_REPO,
            record_type=SourceRecordType.PR,
            external_id="99",
            title="Ambiguous PR",
            url="https://github.com/acme/repo-a/pull/99",
        )
        amb_issue_99 = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src_a.id,
            source_type=SourceType.GITHUB_REPO,
            record_type=SourceRecordType.ISSUE,
            external_id="99",
            title="Ambiguous Issue",
            url="https://github.com/acme/repo-a/issues/99",
            metadata_json={"is_pull_request": False},
        )
        # Different repo src_b has ISSUE #42 -> MUST NOT touch across repos
        other_repo_issue_42 = SourceRecord(
            id=uuid.uuid4(),
            connected_source_id=src_b.id,
            source_type=SourceType.GITHUB_REPO,
            record_type=SourceRecordType.ISSUE,
            external_id="42",
            title="Upgrade TLS cipher list",
            url="https://github.com/acme/repo-b/pull/42",
            metadata_json={"is_pull_request": True},
        )
        session.add_all([pr_42, dup_issue_42, amb_pr_99, amb_issue_99, other_repo_issue_42])
        session.flush()

        # Evidence and Events attached to duplicate ISSUE #42 (+ 1 colliding event on pr_42)
        ev_on_pr = SourceEvent(
            id=uuid.uuid4(),
            record_id=pr_42.id,
            event_type="comment",
            external_id="c-shared",
            body="Shared comment",
        )
        ev_dup_collision = SourceEvent(
            id=uuid.uuid4(),
            record_id=dup_issue_42.id,
            event_type="comment",
            external_id="c-shared",
            body="Shared comment",
        )
        ev_unique_on_dup = SourceEvent(
            id=uuid.uuid4(),
            record_id=dup_issue_42.id,
            event_type="comment",
            external_id="c-unique-issue-comment",
            body="Preserved comment only on dup issue",
        )
        session.add_all([ev_on_pr, ev_dup_collision, ev_unique_on_dup])

        case = HandoverCase(
            id=uuid.uuid4(),
            project_id=proj.id,
            case_number=1,
            title="Gap 6 Dedup Case",
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.DRAFT,
            created_by_id=maya.id,
        )
        session.add(case)
        session.flush()
        pack = TransferPack(
            id=uuid.uuid4(),
            case_id=case.id,
            name="Primary Pack",
            is_primary=True,
            status=TransferPackStatus.DRAFT,
        )
        session.add(pack)
        session.flush()
        claim = Claim(
            id=uuid.uuid4(),
            transfer_pack_id=pack.id,
            claim_type=ClaimType.DECISION,
            title="TLS cipher upgrade",
            body_text="Upgraded ciphers in PR 42",
            evidence_state=EvidenceState.SUPPORTED,
        )
        session.add(claim)
        session.flush()
        evidence = ClaimEvidence(
            id=uuid.uuid4(),
            claim_id=claim.id,
            source_record_id=dup_issue_42.id,
            excerpt="Duplicate issue payload",
            locator="github:issue:42",
        )
        session.add(evidence)
        session.commit()

        # 1. Unauthorized reviewer/contributor denied
        with pytest.raises(PermissionError):
            cleanup_duplicate_github_records(
                session, actor_id=kabir.id, project_id=proj.id, dry_run=True
            )
        with pytest.raises(PermissionError):
            cleanup_duplicate_github_records(
                session, actor_id=aisha.id, project_id=proj.id, dry_run=False
            )

        # 2. Dry-run makes zero mutations
        dry = cleanup_duplicate_github_records(
            session, actor_id=maya.id, project_id=proj.id, dry_run=True
        )
        assert dry["dry_run"] is True
        assert dry["safe_duplicate_count"] == 1
        assert dry["ambiguous_count"] == 1
        assert dry["duplicates_deleted"] == 0
        assert session.query(SourceRecord).filter(SourceRecord.id == dup_issue_42.id).first() is not None

        # 3. Apply cleanup atomically
        applied = cleanup_duplicate_github_records(
            session, actor_id=maya.id, project_id=proj.id, dry_run=False
        )
        assert applied["dry_run"] is False
        assert applied["duplicates_deleted"] == 1
        assert applied["evidence_relinked"] == 1
        assert applied["events_relinked"] == 1
        assert applied["duplicate_events_removed"] == 1
        assert applied["ambiguous_count"] == 1

        session.expire_all()
        assert session.query(SourceRecord).filter(SourceRecord.id == dup_issue_42.id).first() is None
        assert session.query(SourceRecord).filter(SourceRecord.id == pr_42.id).first() is not None
        assert session.query(SourceRecord).filter(SourceRecord.id == amb_issue_99.id).first() is not None
        assert session.query(SourceRecord).filter(SourceRecord.id == other_repo_issue_42.id).first() is not None

        relinked_ev = session.query(ClaimEvidence).filter(ClaimEvidence.id == evidence.id).first()
        assert relinked_ev.source_record_id == pr_42.id

        moved_event = session.query(SourceEvent).filter(SourceEvent.id == ev_unique_on_dup.id).first()
        assert moved_event is not None and moved_event.record_id == pr_42.id

        audit = session.query(AuditEvent).filter(
            AuditEvent.action == "source.deduplicated",
            AuditEvent.entity_id == proj.id,
        ).first()
        assert audit is not None

        # 4. Idempotent repeat run deletes nothing further
        repeat = cleanup_duplicate_github_records(
            session, actor_id=maya.id, project_id=proj.id, dry_run=False
        )
        assert repeat["safe_duplicate_count"] == 0
        assert repeat["duplicates_deleted"] == 0
        assert repeat["ambiguous_count"] == 1

        # 5. CLI dry-run & non-lead exit code 2 work cleanly
        from scripts.deduplicate_github_records import main as dedup_cli_main

        assert dedup_cli_main(["--actor-email", "aisha.khan@example.test", "--project-id", str(proj.id)]) == 2
        assert dedup_cli_main(["--actor-email", "maya.sharma@example.test", "--project-id", str(proj.id)]) == 0

        # 6. Local freshness makes ZERO remote HTTP calls and reports local semantics
        outbound_calls = []
        monkeypatch.setattr(httpx, "get", lambda *a, **kw: outbound_calls.append(a))
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: outbound_calls.append(a))
        fresh = refresh_source(session, source_id=src_a.id, actor_id=maya.id, simulate_modification=False)
        assert outbound_calls == []
        assert fresh["is_local_only"] is True
        assert fresh["freshness_basis"] == "local_timestamps"
    finally:
        session.close()
