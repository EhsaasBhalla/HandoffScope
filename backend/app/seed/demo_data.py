"""Synthetic fixture data — ~60 source records, documents, packs, claims, version, shares, and acceptance for demo scenario.

Phase 10 — Hardening & Demo.
Creates a complete, realistic project history and handover case for the Atlas Platform handover demo.
Scenario: Arjun is departing; Maya is lead; Kabir is reviewer; Aisha is successor.
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
    ClaimType,
    ConnectionStatus,
    EvidenceState,
    EvidenceType,
    Freshness,
    Priority,
    ProcessingStatus,
    QuestionResponseReviewState,
    QuestionStatus,
    ReviewState,
    Sensitivity,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
    TransitionType,
)
from app.modules.audit.service import create_audit_event
from app.modules.audit.models import AuditEvent
from app.modules.documents.models import Document
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.questions.models import Question, QuestionResponse
from app.modules.recipients.models import (
    RecipientAcknowledgement,
    ResponsibilityAcceptance,
    ResponsibilityAssignment,
)
from app.modules.reviews.models import HandoverVersion
from app.modules.sharing.models import ShareGrant
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.seed.fixture")

NOW = datetime.now(timezone.utc)
DAY = timedelta(days=1)


def seed_synthetic_fixture(db: Session) -> None:
    """Create the full synthetic fixture and complete judge demo case."""
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

    if not all([arjun, maya, neha, kabir, aisha]):
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

    # Check if records already exist
    existing_records = db.query(SourceRecord).filter(
        SourceRecord.connected_source_id == source.id
    ).all()

    record_map: dict[str, SourceRecord] = {r.external_id: r for r in existing_records}

    if not existing_records:
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
                external_id=f"issue-{issue['num']}",
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
                metadata_json={"labels": issue["labels"], "is_pull_request": False, "issue_number": issue["num"]},
            )
            db.add(record)
            record_map[f"issue-{issue['num']}"] = record

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
                external_id=f"pr-{pr['num']}",
                title=pr["title"],
                body=f"PR #{pr['num']}: {pr['title']}\n\n## Changes\nDetailed PR description.\n\nCloses #{pr['num'].replace('10', '')}",
                author_external_id=pr["author"],
                author_name=author.display_name if author else pr["author"],
                state="merged" if pr["merged"] else pr["state"],
                url=f"https://github.com/acme-eng/atlas-platform/pull/{pr['num']}",
                sensitivity=Sensitivity.GENERAL,
                processing_status=ProcessingStatus.COMPLETED,
                external_created_at=NOW - (pr["days_ago"] * DAY),
                external_updated_at=NOW - (max(pr["days_ago"] - 3, 1) * DAY),
                metadata_json={"labels": pr["labels"], "is_pull_request": True, "merged": pr["merged"], "pr_number": pr["num"]},
            )
            db.add(record)
            record_map[f"pr-{pr['num']}"] = record

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
                external_id=f"commit-{sha}",
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
            record_map[f"commit-{sha}"] = record

        db.flush()

    # ── Documents (5) including 1 Restricted ───────────────────
    docs_data = [
        {
            "filename": "auth_arch_spec.md",
            "title": "Atlas Auth Service Architecture & JWT Specification",
            "sensitivity": Sensitivity.GENERAL,
            "text": "The Atlas Authentication API enforces RS256 JWT tokens. Claims are signed with 4096-bit RSA keys rotated quarterly.",
        },
        {
            "filename": "payment_contract_v1.2.md",
            "title": "Payment Gateway Integration Contract v1.2",
            "sensitivity": Sensitivity.INTERNAL,
            "text": "Contract specification for payment processing. Payment service delegates tenant authentication to the core auth service.",
        },
        {
            "filename": "db_migration_runbook.md",
            "title": "Database Schema Migration Runbook v2",
            "sensitivity": Sensitivity.GENERAL,
            "text": "Runbook for database migrations. Note: Runbook last updated 4 months ago and predates schema v2 tenant indexing.",
        },
        {
            "filename": "deployment_staging_runbook.md",
            "title": "Deployment & Staging Environment Runbook",
            "sensitivity": Sensitivity.GENERAL,
            "text": "Staging environment deployed on AWS us-east-1 via Terraform. Automated production promotion pipeline is pending approval.",
        },
        {
            "filename": "vault_cloud_credentials_runbook.md",
            "title": "Production Vault Access & Cloud Credentials Runbook",
            "sensitivity": Sensitivity.RESTRICTED,
            "text": "CONFIDENTIAL: Production HashiCorp Vault root credentials and AWS IAM production root access. Strictly restricted to Project Leads and Workspace Admins.",
        },
    ]

    doc_models = {}
    for d in docs_data:
        doc = db.query(Document).filter(
            Document.project_id == project.id,
            Document.original_filename == d["filename"],
        ).first()
        if not doc:
            doc = Document(
                project_id=project.id,
                filename=d["filename"],
                original_filename=d["filename"],
                mime_type="text/markdown",
                file_size=len(d["text"]),
                storage_path=f"storage/uploads/{d['filename']}",
                file_hash=f"hash-{d['filename']}",
                processing_status=ProcessingStatus.COMPLETED,
                sensitivity=d["sensitivity"],
                extracted_text=d["text"],
                page_count=1,
                section_count=1,
                uploaded_by_id=maya.id,
            )
            db.add(doc)
            db.flush()
        doc_models[d["filename"]] = doc

    # ── Create or Update Handover Case ────────────────────────
    case = db.query(HandoverCase).filter(
        HandoverCase.project_id == project.id,
        HandoverCase.case_number == 1,
    ).first()

    if not case:
        case = HandoverCase(
            project_id=project.id,
            case_number=1,
            title="Arjun Patel - Atlas Platform Handover",
            description=(
                "Planned departure handover for Arjun Patel, primary contributor to "
                "the Atlas Platform auth service, cache layer, and payment integration. "
                "Aisha Khan is the designated successor."
            ),
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.PARTIALLY_ACKNOWLEDGED,
            sync_status=CaseSyncStatus.CURRENT,
            scope_start=(NOW - 90 * DAY).date(),
            scope_end=NOW.date(),
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()

        participants = [
            (maya.id, CaseParticipantRole.INITIATOR),
            (arjun.id, CaseParticipantRole.DEPARTING),
            (kabir.id, CaseParticipantRole.REVIEWER),
            (aisha.id, CaseParticipantRole.RECIPIENT),
            (neha.id, CaseParticipantRole.CONTRIBUTOR),
        ]
        for user_id, role in participants:
            db.add(CaseParticipant(case_id=case.id, user_id=user_id, role=role))
    else:
        case.status = CaseStatus.PARTIALLY_ACKNOWLEDGED
        case.sync_status = CaseSyncStatus.CURRENT

    db.flush()

    # ── Seed Transfer Packs & Claims (4 Packs) ────────────────
    packs_def = [
        {
            "name": "Authentication API & Multi-Tenancy",
            "description": "Core auth middleware, user registration, JWT lifecycle, and multi-tenant isolation.",
            "status": TransferPackStatus.APPROVED,
            "claims": [
                {
                    "title": "JWT middleware enforces RS256 token verification across all tenant-scoped routes",
                    "claim_type": ClaimType.WORK_ITEM,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": ["pr-101", "commit-abc0002"],
                },
                {
                    "title": "User registration endpoint implements argon2 password hashing with rate-limiting",
                    "claim_type": ClaimType.WORK_ITEM,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": ["pr-102", "commit-abc0005"],
                },
                {
                    "title": "Architecture Decision: Microservices vs Monolith for Auth boundary",
                    "claim_type": ClaimType.DECISION,
                    "evidence_state": EvidenceState.CONFLICTING,
                    "review_state": ReviewState.NEEDS_CLARIFICATION,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.CRITICAL,
                    "records": ["issue-3", "issue-13"],
                },
                {
                    "title": "Multi-tenant auth middleware refactored to extract tenant ID from subdomain",
                    "claim_type": ClaimType.WORK_ITEM,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.EDITED_AND_ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.MEDIUM,
                    "records": ["pr-107", "commit-abc0013"],
                },
                {
                    "title": "Production deployment testing & multi-region latency benchmarks",
                    "claim_type": ClaimType.KNOWLEDGE_GAP,
                    "evidence_state": EvidenceState.UNKNOWN,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": [],
                    "unknown_reason": "No evidence of production deployment testing or latency benchmarks found in repository or runbooks.",
                },
            ],
        },
        {
            "name": "Payment Integration Service",
            "description": "Payment gateway client, webhooks, circuit breaker, and retry policies.",
            "status": TransferPackStatus.APPROVED,
            "claims": [
                {
                    "title": "Payment service client has circuit breaker and exponential backoff retry logic",
                    "claim_type": ClaimType.WORK_ITEM,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": ["pr-109", "commit-abc0032"],
                },
                {
                    "title": "Dependency: Payment service is tightly coupled to Auth service tenant token exchange",
                    "claim_type": ClaimType.DEPENDENCY,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.CRITICAL,
                    "records": ["issue-14", "commit-abc0025"],
                },
                {
                    "title": "Payment contract API specification is in draft state pending vendor webhook confirmation",
                    "claim_type": ClaimType.RISK,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": ["issue-8"],
                    "doc": "payment_contract_v1.2.md",
                },
                {
                    "title": "Production webhook signature verification key rotation runbook missing",
                    "claim_type": ClaimType.KNOWLEDGE_GAP,
                    "evidence_state": EvidenceState.UNKNOWN,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": [],
                    "unknown_reason": "Vendor webhook secret rotation procedure has no documented runbook.",
                },
            ],
        },
        {
            "name": "Database Migrations & Schema v2",
            "description": "Alembic schema migrations, tenant indexing, and database runbooks.",
            "status": TransferPackStatus.APPROVED,
            "claims": [
                {
                    "title": "Schema v2 migration executed; user tenant_id index added",
                    "claim_type": ClaimType.WORK_ITEM,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": ["pr-110", "commit-abc0017"],
                },
                {
                    "title": "Deployment runbook is stale (last updated 4 months ago, predates v2 schema migration)",
                    "claim_type": ClaimType.RISK,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.POTENTIALLY_STALE,
                    "priority": Priority.HIGH,
                    "records": ["commit-abc0022"],
                    "doc": "db_migration_runbook.md",
                },
                {
                    "title": "Rollback procedure for multi-tenant table partitions not documented",
                    "claim_type": ClaimType.KNOWLEDGE_GAP,
                    "evidence_state": EvidenceState.UNKNOWN,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.MEDIUM,
                    "records": [],
                    "unknown_reason": "No automated or documented downgrade script for multi-tenant partition tables.",
                },
            ],
        },
        {
            "name": "Deployment Operations & Staging",
            "description": "Terraform staging configs, deployment runbooks, and cloud infrastructure.",
            "status": TransferPackStatus.APPROVED,
            "claims": [
                {
                    "title": "Terraform configuration provisions staging environment on AWS us-east-1",
                    "claim_type": ClaimType.WORK_ITEM,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.MEDIUM,
                    "records": ["commit-abc0011"],
                    "doc": "deployment_staging_runbook.md",
                },
                {
                    "title": "Automated production promotion pipeline not yet configured; manual approval gate required",
                    "claim_type": ClaimType.RISK,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.HIGH,
                    "records": ["issue-16"],
                },
                {
                    "title": "Production root credentials and KMS encryption keys access",
                    "claim_type": ClaimType.OPERATIONAL_NOTE,
                    "evidence_state": EvidenceState.SUPPORTED,
                    "review_state": ReviewState.ACCEPTED,
                    "freshness": Freshness.CURRENT,
                    "priority": Priority.CRITICAL,
                    "records": [],
                    "doc": "vault_cloud_credentials_runbook.md",
                    "is_restricted": True,
                },
            ],
        },
    ]

    pack_models = []
    for p_idx, p_data in enumerate(packs_def):
        pack = db.query(TransferPack).filter(
            TransferPack.case_id == case.id,
            TransferPack.name == p_data["name"],
        ).first()

        if not pack:
            pack = TransferPack(
                case_id=case.id,
                name=p_data["name"],
                description=p_data["description"],
                status=p_data["status"],
                recorded_owner_id=arjun.id,
                suggested_successor_id=aisha.id,
                sort_order=p_idx,
            )
            db.add(pack)
            db.flush()

        pack_models.append(pack)

        # Claims for this pack
        for c_data in p_data["claims"]:
            existing_claim = db.query(Claim).filter(
                Claim.transfer_pack_id == pack.id,
                Claim.title == c_data["title"],
            ).first()

            if not existing_claim:
                claim = Claim(
                    transfer_pack_id=pack.id,
                    claim_type=c_data["claim_type"],
                    title=c_data["title"],
                    body_text=c_data.get("unknown_reason") or f"Reconstructed statement for {c_data['title']}",
                    evidence_state=c_data["evidence_state"],
                    freshness=c_data["freshness"],
                    review_state=c_data["review_state"],
                    priority=c_data["priority"],
                    reviewed_by=kabir.id if c_data["review_state"] != ReviewState.PENDING_REVIEW else None,
                    reviewed_at=NOW.isoformat() if c_data["review_state"] != ReviewState.PENDING_REVIEW else None,
                )
                db.add(claim)
                db.flush()

                # Add evidence items
                for rec_key in c_data.get("records", []):
                    rec = record_map.get(rec_key)
                    if rec:
                        ce = ClaimEvidence(
                            claim_id=claim.id,
                            source_record_id=rec.id,
                            evidence_type=EvidenceType.DIRECT_REFERENCE,
                            locator=f"{rec.record_type.value}:{rec.external_id}",
                            excerpt=f"Citing {rec.title}",
                            is_restricted=False,
                        )
                        db.add(ce)

                if c_data.get("doc"):
                    doc = doc_models.get(c_data["doc"])
                    if doc:
                        is_restr = c_data.get("is_restricted", False) or (doc.sensitivity == Sensitivity.RESTRICTED)
                        ce = ClaimEvidence(
                            claim_id=claim.id,
                            document_id=doc.id,
                            evidence_type=EvidenceType.DIRECT_REFERENCE,
                            locator=f"DOC:{doc.original_filename}",
                            excerpt=doc.extracted_text[:120] if doc.extracted_text else None,
                            is_restricted=is_restr,
                        )
                        db.add(ce)

    db.flush()

    # ── Questions & Answers ───────────────────────────────────
    q = db.query(Question).filter(
        Question.case_id == case.id,
        Question.question_text.ilike("%deployment process%"),
    ).first()
    if not q:
        q = Question(
            case_id=case.id,
            transfer_pack_id=pack_models[0].id,
            question_text="What is the current deployment process for the auth service?",
            why_it_matters="Clarifies production manual deployment steps and required cloud credentials.",
            suggested_respondent_id=arjun.id,
            assigned_to_id=arjun.id,
            priority=Priority.HIGH,
            status=QuestionStatus.ANSWERED,
            created_by_id=maya.id,
        )
        db.add(q)
        db.flush()

        qr = QuestionResponse(
            question_id=q.id,
            respondent_id=arjun.id,
            response_text=(
                "Currently deployed via `./scripts/deploy-staging.sh` with manual AWS credentials injection. "
                "Production requires Lead sign-off in Slack before manual deploy."
            ),
            review_state=QuestionResponseReviewState.ACCEPTED,
            reviewed_by_id=maya.id,
            reviewed_at=NOW.isoformat(),
        )
        db.add(qr)
        db.flush()

    # ── Immutable Handover Version (v1) ───────────────────────
    version = db.query(HandoverVersion).filter(
        HandoverVersion.case_id == case.id,
        HandoverVersion.version_number == 1,
    ).first()

    if not version:
        snapshot_payload = {
            "version_number": 1,
            "case_id": str(case.id),
            "approved_at": NOW.isoformat(),
            "approved_by": "Kabir Singh",
            "packs": [
                {
                    "name": p.name,
                    "description": p.description,
                    "claims_count": len(p.claims),
                }
                for p in pack_models
            ],
        }
        version = HandoverVersion(
            case_id=case.id,
            version_number=1,
            approved_by_id=kabir.id,
            approved_at=NOW,
            is_current=True,
            snapshot_json=snapshot_payload,
        )
        db.add(version)
        db.flush()

    # ── Version Share Grant to Aisha Khan ─────────────────────
    share_grant = db.query(ShareGrant).filter(
        ShareGrant.handover_version_id == version.id,
        ShareGrant.recipient_user_id == aisha.id,
    ).first()

    if not share_grant:
        share_grant = ShareGrant(
            handover_version_id=version.id,
            recipient_user_id=aisha.id,
            granted_by=maya.id,
        )
        db.add(share_grant)
        db.flush()

    # ── Recipient Acknowledgement ─────────────────────────────
    ack = db.query(RecipientAcknowledgement).filter(
        RecipientAcknowledgement.share_grant_id == share_grant.id,
        RecipientAcknowledgement.user_id == aisha.id,
    ).first()

    if not ack:
        ack = RecipientAcknowledgement(
            share_grant_id=share_grant.id,
            handover_version_id=version.id,
            user_id=aisha.id,
            acknowledged_at=NOW,
        )
        db.add(ack)
        db.flush()

    # ── Responsibility Assignments (One Accepted, One Declined)
    from app.db.enums import ResponsibilityAcceptanceStatus

    # Pack 1 (Auth API): Accepted
    assign_p1 = db.query(ResponsibilityAssignment).filter(
        ResponsibilityAssignment.transfer_pack_id == pack_models[0].id,
        ResponsibilityAssignment.assigned_user_id == aisha.id,
    ).first()

    if not assign_p1:
        assign_p1 = ResponsibilityAssignment(
            transfer_pack_id=pack_models[0].id,
            handover_version_id=version.id,
            assigned_user_id=aisha.id,
            assigned_by=maya.id,
        )
        db.add(assign_p1)
        db.flush()

        acceptance_p1 = ResponsibilityAcceptance(
            responsibility_assignment_id=assign_p1.id,
            user_id=aisha.id,
            status=ResponsibilityAcceptanceStatus.ACCEPTED,
            responded_at=NOW,
        )
        db.add(acceptance_p1)
        pack_models[0].status = TransferPackStatus.ACCEPTED

    # Pack 2 (Payment Integration): Declined
    assign_p2 = db.query(ResponsibilityAssignment).filter(
        ResponsibilityAssignment.transfer_pack_id == pack_models[1].id,
        ResponsibilityAssignment.assigned_user_id == aisha.id,
    ).first()

    if not assign_p2:
        assign_p2 = ResponsibilityAssignment(
            transfer_pack_id=pack_models[1].id,
            handover_version_id=version.id,
            assigned_user_id=aisha.id,
            assigned_by=maya.id,
        )
        db.add(assign_p2)
        db.flush()

        acceptance_p2 = ResponsibilityAcceptance(
            responsibility_assignment_id=assign_p2.id,
            user_id=aisha.id,
            status=ResponsibilityAcceptanceStatus.DECLINED,
            responded_at=NOW,
            decline_reason="Need additional training on the payment gateway SDK before taking sole ownership.",
        )
        db.add(acceptance_p2)
        pack_models[1].status = TransferPackStatus.APPROVED

    # Pack 3 & 4: Pending acceptance
    for p in pack_models[2:]:
        assign_p = db.query(ResponsibilityAssignment).filter(
            ResponsibilityAssignment.transfer_pack_id == p.id,
            ResponsibilityAssignment.assigned_user_id == aisha.id,
        ).first()
        if not assign_p:
            assign_p = ResponsibilityAssignment(
                transfer_pack_id=p.id,
                handover_version_id=version.id,
                assigned_user_id=aisha.id,
                assigned_by=maya.id,
            )
            db.add(assign_p)
            db.flush()

            acceptance_p = ResponsibilityAcceptance(
                responsibility_assignment_id=assign_p.id,
                user_id=aisha.id,
                status=ResponsibilityAcceptanceStatus.PENDING_ACCEPTANCE,
            )
            db.add(acceptance_p)


    db.flush()

    # ── Realistic Audit Trail ─────────────────────────────────
    existing_audits = db.query(AuditEvent).count()
    if existing_audits < 5:
        audit_events = [
            (maya.id, "case.created", "handover_case", case.id, "Created handover case #1 for Arjun Patel"),
            (maya.id, "source.connected", "connected_source", source.id, "Connected Atlas Platform Synthetic History"),
            (maya.id, "reconstruction.completed", "handover_case", case.id, "AI Reconstruction generated 4 Transfer Packs and 14 claims"),
            (kabir.id, "claim.reviewed", "claim", None, "Reviewed and accepted Authentication API claims"),
            (kabir.id, "version.created", "handover_version", version.id, "Approved Handover Version v1 immutable snapshot"),
            (maya.id, "version.shared", "share_grant", share_grant.id, "Granted read access to Aisha Khan for version v1"),
            (aisha.id, "case.acknowledged", "recipient_acknowledgement", ack.id, "Aisha Khan formally acknowledged handover receipt"),
            (aisha.id, "responsibility.accepted", "responsibility_assignment", assign_p1.id, "Aisha Khan accepted ownership of Authentication API"),
            (aisha.id, "responsibility.declined", "responsibility_assignment", assign_p2.id, "Aisha Khan declined Payment Integration (needs training)"),
        ]
        for actor_id, action, entity_type, entity_id, summary in audit_events:
            create_audit_event(
                db,
                actor_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=summary,
            )

    db.commit()
    logger.info("Complete synthetic demo dataset seeded: 4 packs, 14 claims, 1 version, 1 share grant, 2 responsibility decisions, audit log complete")
