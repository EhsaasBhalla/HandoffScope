"""Synthetic fixture data — ~60 source records for demo scenario.

Creates a realistic project history for the Atlas Platform handover demo.
Scenario: Arjun is departing; Maya is lead; Neha is successor.

Ground-truth facts:
- Auth PR (#7) merged but linked issue (#12) still open
- Deployment runbook (doc) is stale — last updated 4 months ago
- Payment service depends on auth service
- Missing test confirmation for cache refactor (#15)
- Conflicting architecture decisions between Arjun (#3) and Kabir (#5)
- 1 restricted HR-related document
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    CaseSyncStatus,
    ConnectionStatus,
    ProcessingStatus,
    Sensitivity,
    SourceRecordType,
    SourceType,
    TransitionType,
)
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.ingestion.models import SourceEvent, SourceRecord
from app.modules.projects.models import Project
from app.modules.sources.models import ConnectedSource
from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.seed.fixture")

NOW = datetime.now(timezone.utc)
DAY = timedelta(days=1)


def seed_synthetic_fixture(db: Session) -> None:
    """Create the full synthetic fixture for the demo."""
    # Look up existing project and users
    project = db.query(Project).filter(Project.slug == "atlas-platform").first()
    if not project:
        logger.warning("Project 'atlas-platform' not found — run demo_seed first")
        return

    users = {}
    for email in [
        "maya.sharma@example.test", "arjun.patel@example.test",
        "neha.gupta@example.test", "kabir.singh@example.test",
        "aisha.khan@example.test", "dev.mehta@example.test",
        "priya.nair@example.test",
    ]:
        u = db.query(User).filter(User.email == email).first()
        if u:
            users[email.split("@")[0].replace(".", "_")] = u

    arjun = users.get("arjun_patel")
    maya = users.get("maya_sharma")
    neha = users.get("neha_gupta")
    kabir = users.get("kabir_singh")
    aisha = users.get("aisha_khan")
    dev_ = users.get("dev_mehta")

    if not all([arjun, maya, neha]):
        logger.warning("Required users not found — run demo_seed first")
        return

    # ── Create Connected Source (Synthetic Fixture) ────────────
    source = db.query(ConnectedSource).filter(
        ConnectedSource.project_id == project.id,
        ConnectedSource.source_type == SourceType.SYNTHETIC_FIXTURE,
    ).first()

    if not source:
        source = ConnectedSource(
            project_id=project.id,
            source_type=SourceType.SYNTHETIC_FIXTURE,
            name="Atlas Platform Synthetic History",
            external_id="atlas-platform-fixture",
            connection_status=ConnectionStatus.ACTIVE,
            config={"fixture_version": "1.0", "ground_truth": True},
            connected_by_id=maya.id,
        )
        db.add(source)
        db.flush()
        logger.info("Created synthetic fixture source")
    else:
        logger.info("Synthetic fixture source already exists")
        # Skip if records already exist
        existing_count = db.query(SourceRecord).filter(
            SourceRecord.connected_source_id == source.id
        ).count()
        if existing_count > 0:
            logger.info("Fixture records already exist (%d), skipping", existing_count)
            return

    # ── Issues (18) ───────────────────────────────────────────
    issues = [
        {"num": "1", "title": "Set up auth service JWT middleware", "author": "arjun_patel", "state": "closed", "labels": ["auth", "backend"], "days_ago": 90},
        {"num": "2", "title": "Implement user registration flow", "author": "arjun_patel", "state": "closed", "labels": ["auth", "api"], "days_ago": 85},
        {"num": "3", "title": "Migrate to microservice architecture", "author": "arjun_patel", "state": "closed", "labels": ["architecture", "decision"], "days_ago": 80},
        {"num": "4", "title": "Add rate limiting to public endpoints", "author": "kabir_singh", "state": "closed", "labels": ["security", "backend"], "days_ago": 75},
        {"num": "5", "title": "Evaluate monolith-first approach for payment service", "author": "kabir_singh", "state": "open", "labels": ["architecture", "decision", "payment"], "days_ago": 70},
        {"num": "6", "title": "Cache invalidation strategy for user sessions", "author": "arjun_patel", "state": "closed", "labels": ["cache", "performance"], "days_ago": 65},
        {"num": "7", "title": "Refactor auth middleware for multi-tenant support", "author": "arjun_patel", "state": "closed", "labels": ["auth", "refactor"], "days_ago": 50},
        {"num": "8", "title": "Payment service integration API design", "author": "arjun_patel", "state": "open", "labels": ["payment", "api", "dependency"], "days_ago": 45},
        {"num": "9", "title": "Database migration plan for v2 schema", "author": "dev_mehta", "state": "closed", "labels": ["database", "migration"], "days_ago": 40},
        {"num": "10", "title": "Add OpenTelemetry tracing", "author": "neha_gupta", "state": "closed", "labels": ["observability", "devops"], "days_ago": 35},
        {"num": "11", "title": "Fix session expiry race condition", "author": "arjun_patel", "state": "closed", "labels": ["bug", "auth", "critical"], "days_ago": 30},
        {"num": "12", "title": "Update auth service documentation for multi-tenant flow", "author": "arjun_patel", "state": "open", "labels": ["docs", "auth"], "days_ago": 25},
        {"num": "13", "title": "Evaluate GraphQL vs REST for internal APIs", "author": "kabir_singh", "state": "open", "labels": ["architecture", "decision"], "days_ago": 20},
        {"num": "14", "title": "Dependency audit: auth service → payment service coupling", "author": "arjun_patel", "state": "open", "labels": ["dependency", "risk"], "days_ago": 15},
        {"num": "15", "title": "Cache refactor test coverage gap", "author": "arjun_patel", "state": "open", "labels": ["testing", "risk", "cache"], "days_ago": 10},
        {"num": "16", "title": "Set up staging environment for auth service", "author": "dev_mehta", "state": "closed", "labels": ["devops", "auth"], "days_ago": 60},
        {"num": "17", "title": "API versioning strategy decision", "author": "arjun_patel", "state": "closed", "labels": ["api", "decision"], "days_ago": 55},
        {"num": "18", "title": "Performance regression in user lookup query", "author": "neha_gupta", "state": "open", "labels": ["bug", "performance"], "days_ago": 5},
    ]

    for issue in issues:
        author = users.get(issue["author"])
        record = SourceRecord(
            connected_source_id=source.id,
            source_type="GITHUB_REPO",
            record_type=SourceRecordType.ISSUE,
            external_id=issue["num"],
            title=issue["title"],
            body=f"Issue #{issue['num']}: {issue['title']}\n\nDetailed description for the synthetic fixture.",
            author_external_id=issue["author"],
            author_name=author.display_name if author else issue["author"],
            state=issue["state"],
            url=f"https://github.com/acme-eng/atlas-platform/issues/{issue['num']}",
            sensitivity=Sensitivity.GENERAL,
            processing_status=ProcessingStatus.COMPLETED,
            external_created_at=NOW - (issue["days_ago"] * DAY),
            external_updated_at=NOW - (max(issue["days_ago"] - 5, 1) * DAY),
            metadata_json={"labels": issue["labels"], "is_pull_request": False},
        )
        db.add(record)

    db.flush()

    # ── Pull Requests (10) ────────────────────────────────────
    prs = [
        {"num": "101", "title": "feat: JWT middleware implementation", "author": "arjun_patel", "state": "closed", "labels": ["auth"], "days_ago": 88, "merged": True},
        {"num": "102", "title": "feat: user registration API", "author": "arjun_patel", "state": "closed", "labels": ["auth", "api"], "days_ago": 82, "merged": True},
        {"num": "103", "title": "refactor: extract auth service to separate module", "author": "arjun_patel", "state": "closed", "labels": ["architecture"], "days_ago": 78, "merged": True},
        {"num": "104", "title": "feat: rate limiting middleware", "author": "kabir_singh", "state": "closed", "labels": ["security"], "days_ago": 73, "merged": True},
        {"num": "105", "title": "feat: session cache with Redis", "author": "arjun_patel", "state": "closed", "labels": ["cache"], "days_ago": 63, "merged": True},
        {"num": "106", "title": "feat: OpenTelemetry integration", "author": "neha_gupta", "state": "closed", "labels": ["observability"], "days_ago": 33, "merged": True},
        {"num": "107", "title": "fix: multi-tenant auth middleware refactor", "author": "arjun_patel", "state": "closed", "labels": ["auth", "refactor"], "days_ago": 48, "merged": True},
        {"num": "108", "title": "fix: session expiry race condition", "author": "arjun_patel", "state": "closed", "labels": ["bug", "auth"], "days_ago": 28, "merged": True},
        {"num": "109", "title": "feat: payment service client skeleton", "author": "arjun_patel", "state": "open", "labels": ["payment"], "days_ago": 12, "merged": False},
        {"num": "110", "title": "chore: database schema v2 migration", "author": "dev_mehta", "state": "closed", "labels": ["database"], "days_ago": 38, "merged": True},
    ]

    for pr in prs:
        author = users.get(pr["author"])
        record = SourceRecord(
            connected_source_id=source.id,
            source_type="GITHUB_REPO",
            record_type=SourceRecordType.PR,
            external_id=pr["num"],
            title=pr["title"],
            body=f"PR #{pr['num']}: {pr['title']}\n\n## Changes\nDetailed PR description for the synthetic fixture.\n\nCloses #{pr['num'].replace('10', '')}",
            author_external_id=pr["author"],
            author_name=author.display_name if author else pr["author"],
            state="merged" if pr["merged"] else pr["state"],
            url=f"https://github.com/acme-eng/atlas-platform/pull/{pr['num']}",
            sensitivity=Sensitivity.GENERAL,
            processing_status=ProcessingStatus.COMPLETED,
            external_created_at=NOW - (pr["days_ago"] * DAY),
            external_updated_at=NOW - (max(pr["days_ago"] - 3, 1) * DAY),
            metadata_json={
                "labels": pr["labels"],
                "is_pull_request": True,
                "merged": pr["merged"],
            },
        )
        db.add(record)

    db.flush()

    # ── Commits (35) ──────────────────────────────────────────
    commit_messages = [
        ("abc0001", "Initial auth service setup", "arjun_patel", 89),
        ("abc0002", "Add JWT token generation", "arjun_patel", 88),
        ("abc0003", "Add token validation middleware", "arjun_patel", 87),
        ("abc0004", "User registration endpoint", "arjun_patel", 83),
        ("abc0005", "Add password hashing with argon2", "arjun_patel", 82),
        ("abc0006", "Extract auth module to separate package", "arjun_patel", 79),
        ("abc0007", "Add rate limiter using Redis", "kabir_singh", 74),
        ("abc0008", "Configure rate limit per endpoint", "kabir_singh", 73),
        ("abc0009", "Redis session cache implementation", "arjun_patel", 64),
        ("abc0010", "Cache invalidation on password change", "arjun_patel", 63),
        ("abc0011", "Set up staging env Terraform", "dev_mehta", 61),
        ("abc0012", "API versioning with URL prefix", "arjun_patel", 56),
        ("abc0013", "Multi-tenant middleware refactor", "arjun_patel", 49),
        ("abc0014", "Add tenant context to request pipeline", "arjun_patel", 48),
        ("abc0015", "Payment service API contract draft", "arjun_patel", 44),
        ("abc0016", "Database schema v2 migration scripts", "dev_mehta", 39),
        ("abc0017", "Add index on user.tenant_id", "dev_mehta", 38),
        ("abc0018", "OpenTelemetry span instrumentation", "neha_gupta", 34),
        ("abc0019", "Add trace correlation to logs", "neha_gupta", 33),
        ("abc0020", "Fix race condition in session expiry check", "arjun_patel", 29),
        ("abc0021", "Add mutex lock for concurrent session updates", "arjun_patel", 28),
        ("abc0022", "Update deployment runbook", "arjun_patel", 120),
        ("abc0023", "Auth service integration test suite", "arjun_patel", 85),
        ("abc0024", "Add E2E test for registration flow", "arjun_patel", 84),
        ("abc0025", "Dependency audit: document auth→payment coupling", "arjun_patel", 16),
        ("abc0026", "Add health check endpoint", "kabir_singh", 72),
        ("abc0027", "Configure CI pipeline for auth service", "dev_mehta", 60),
        ("abc0028", "Add Swagger docs generation", "arjun_patel", 55),
        ("abc0029", "Cache refactor: switch from local to Redis", "arjun_patel", 62),
        ("abc0030", "Performance fix: add query plan optimization", "neha_gupta", 6),
        ("abc0031", "Payment client skeleton with retry logic", "arjun_patel", 13),
        ("abc0032", "Add circuit breaker for payment calls", "arjun_patel", 12),
        ("abc0033", "Update README with architecture diagram", "arjun_patel", 77),
        ("abc0034", "Add monitoring dashboard config", "neha_gupta", 32),
        ("abc0035", "Fix flaky test in auth middleware", "arjun_patel", 27),
    ]

    for sha, message, author_key, days_ago in commit_messages:
        author = users.get(author_key)
        record = SourceRecord(
            connected_source_id=source.id,
            source_type="GITHUB_REPO",
            record_type=SourceRecordType.COMMIT,
            external_id=sha,
            title=message,
            body=message,
            author_external_id=author_key,
            author_name=author.display_name if author else author_key,
            state=None,
            url=f"https://github.com/acme-eng/atlas-platform/commit/{sha}",
            sensitivity=Sensitivity.GENERAL,
            processing_status=ProcessingStatus.COMPLETED,
            external_created_at=NOW - (days_ago * DAY),
            external_updated_at=NOW - (days_ago * DAY),
            metadata_json={"sha": sha},
        )
        db.add(record)

    db.flush()

    # ── Create Handover Case ──────────────────────────────────
    existing_case = db.query(HandoverCase).filter(
        HandoverCase.project_id == project.id,
        HandoverCase.case_number == 1,
    ).first()

    if not existing_case:
        case = HandoverCase(
            project_id=project.id,
            case_number=1,
            title="Arjun Patel - Atlas Platform Handover",
            description=(
                "Planned departure handover for Arjun Patel, primary contributor to "
                "the Atlas Platform auth service, cache layer, and payment integration. "
                "Neha Gupta is the designated successor."
            ),
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.RECONSTRUCTING,
            sync_status=CaseSyncStatus.CURRENT,
            scope_start=(NOW - 90 * DAY).date(),
            scope_end=NOW.date(),
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()

        # Add participants
        participants = [
            (maya.id, CaseParticipantRole.INITIATOR),
            (arjun.id, CaseParticipantRole.DEPARTING),
            (aisha.id, CaseParticipantRole.REVIEWER),
            (neha.id, CaseParticipantRole.RECIPIENT),
        ]
        for user_id, role in participants:
            db.add(CaseParticipant(case_id=case.id, user_id=user_id, role=role))

        logger.info("Created demo handover case #1")

    db.commit()
    logger.info("Synthetic fixture seeded: 18 issues, 10 PRs, 35 commits, 1 case")
