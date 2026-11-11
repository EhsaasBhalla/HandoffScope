"""Idempotent demo seed fixtures for Pydantic and Zulip showcase projects.

Ensures both fresh databases (local SQLite / Neon PostgreSQL) and existing
deployments populate realistic source records, runbooks, handover cases,
transfer packs, grounded claims, and Q&A threads for 'pydantic' and 'zulip'.
"""

from __future__ import annotations

import hashlib
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
    SyncRunStatus,
    TransferPackStatus,
    TransitionType,
)
from app.integrations.documents import build_document_section_chunks
from app.modules.documents.models import Document
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, CaseSource, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.questions.models import Question, QuestionResponse
from app.modules.sources.models import ConnectedSource, SyncRun
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.seed.repos")


_PROJECT_SPECS: list[dict] = [
    {
        "slug": "pydantic",
        "source_name": "pydantic/pydantic",
        "case_title": "Pydantic v2 Core Validation & Serialization Handover",
        "case_description": (
            "Architecture and operational handover covering pydantic-core SchemaValidator compilation, "
            "strict-mode JSON parsing, ConfigDict validation hooks, and TypeAdapter caching."
        ),
        "doc_filename": "pydantic_v2_serialization_runbook.md",
        "doc_text": (
            "# Pydantic v2 Operations & Validation Runbook\n\n"
            "## SchemaValidator Compilation & Memory Guard\n"
            "Core validation runs inside compiled Rust SchemaValidator trees built lazily per BaseModel.\n"
            "When recursive self-referencing models fail schema generation, invoke `model_rebuild(force=True)` "
            "after all forward-ref module namespaces are imported.\n\n"
            "## Production JSON Serialization Decision\n"
            "We decided to standardize API responses on `model_validate_json()` and `model_dump(mode='json')` "
            "because bypassing intermediate Python dicts eliminates strict coercion drift and cuts latency by ~3x."
        ),
        "records": [
            {
                "record_type": SourceRecordType.PR,
                "external_id": "9801",
                "title": "Isolate SchemaValidator rebuild hooks for circular BaseModels",
                "body": (
                    "Implements deterministic defer_build resolution so forward-referenced BaseModel graphs "
                    "invoke model_rebuild(force=True) safely without raising PydanticUndefinedAnnotation."
                ),
                "state": "merged",
                "author": "arjun_patel",
                "url": "https://github.com/pydantic/pydantic/pull/9801",
                "days_ago": 14,
            },
            {
                "record_type": SourceRecordType.PR,
                "external_id": "9842",
                "title": "Enforce strict=True fast path inside model_validate_json",
                "body": (
                    "Decision: Keep model_validate_json strict boundary intact when validating external JSON "
                    "payloads, avoiding implicit int-to-str coercion unless strict=False is set in ConfigDict."
                ),
                "state": "merged",
                "author": "arjun_patel",
                "url": "https://github.com/pydantic/pydantic/pull/9842",
                "days_ago": 10,
            },
            {
                "record_type": SourceRecordType.ISSUE,
                "external_id": "9910",
                "title": "ADR: ConfigDict(frozen=True) immutability with custom @model_validator",
                "body": (
                    "Decision: Models representing billing contracts must set frozen=True and run post-init "
                    "invariants in @model_validator(mode='after') rather than mutating attributes in-place."
                ),
                "state": "open",
                "author": "neha_gupta",
                "url": "https://github.com/pydantic/pydantic/issues/9910",
                "days_ago": 6,
            },
            {
                "record_type": SourceRecordType.COMMIT,
                "external_id": "c0f9821a7e4d",
                "title": "perf: Cache TypeAdapter schema builders per generic specialization",
                "body": (
                    "Prevents per-request SchemaValidator recompilation by hoisting module-level TypeAdapter "
                    "instances out of hot request handlers."
                ),
                "state": "committed",
                "author": "arjun_patel",
                "url": "https://github.com/pydantic/pydantic/commit/c0f9821a7e4d",
                "days_ago": 4,
            },
        ],
        "packs": [
            {
                "name": "Validation Core & Schema Compilation",
                "component_area": "Core Runtime",
                "description": "SchemaValidator lifecycle, forward-ref resolution, and strict validation contracts.",
                "is_primary": True,
                "claims": [
                    {
                        "claim_type": ClaimType.DECISION,
                        "title": "Enforce strict JSON boundary via model_validate_json",
                        "body_text": (
                            "External JSON payloads use `model_validate_json()` under `strict=True` defaults "
                            "to avoid unintended implicit type coercion unless opted into per-model `ConfigDict`."
                        ),
                        "evidence_state": EvidenceState.SUPPORTED,
                        "review_state": ReviewState.ACCEPTED,
                        "priority": Priority.HIGH,
                        "rec_ext_id": "9842",
                        "locator": "PR #9842",
                    },
                    {
                        "claim_type": ClaimType.OPERATIONAL_NOTE,
                        "title": "Forward-reference graph resolution runbook",
                        "body_text": (
                            "Circular or deferred `BaseModel` schemas require `model_rebuild(force=True)` once all "
                            "module namespaces have finished importing."
                        ),
                        "evidence_state": EvidenceState.SUPPORTED,
                        "review_state": ReviewState.PENDING_REVIEW,
                        "priority": Priority.HIGH,
                        "rec_ext_id": "9801",
                        "locator": "PR #9801",
                    },
                    {
                        "claim_type": ClaimType.RISK,
                        "title": "Unbounded dynamic TypeAdapter instantiation latency risk",
                        "body_text": (
                            "Instantiating `TypeAdapter(list[Model])` inside per-request loops rebuilds Rust schemas "
                            "repeatedly; reuse module-level cached `TypeAdapter` singletons."
                        ),
                        "evidence_state": EvidenceState.SUPPORTED,
                        "review_state": ReviewState.PENDING_REVIEW,
                        "priority": Priority.MEDIUM,
                        "rec_ext_id": "c0f9821a7e4d",
                        "locator": "Commit c0f9821a",
                    },
                ],
            },
            {
                "name": "Serialization Hooks & ConfigDict Policy",
                "component_area": "Serialization",
                "description": "Immutability rules, validator invariants, and JSON export compatibility.",
                "is_primary": False,
                "claims": [
                    {
                        "claim_type": ClaimType.DECISION,
                        "title": "Use frozen ConfigDict for contract schemas",
                        "body_text": (
                            "Contract schemas must specify `ConfigDict(frozen=True)` with invariant checks inside "
                            "`@model_validator(mode='after')`."
                        ),
                        "evidence_state": EvidenceState.CONFLICTING,
                        "review_state": ReviewState.NEEDS_CLARIFICATION,
                        "priority": Priority.HIGH,
                        "rec_ext_id": "9910",
                        "locator": "Issue #9910",
                    },
                    {
                        "claim_type": ClaimType.WORK_ITEM,
                        "title": "Verify serialization warning telemetry under Python 3.14",
                        "body_text": (
                            "Confirm whether fallback union serializer warnings trigger in staging logs before "
                            "tightening strict schema CI gates."
                        ),
                        "evidence_state": EvidenceState.UNKNOWN,
                        "review_state": ReviewState.PENDING_REVIEW,
                        "priority": Priority.MEDIUM,
                        "rec_ext_id": "doc-pydantic",
                        "locator": "Section 2: Production JSON Serialization Decision",
                    },
                ],
            },
        ],
        "questions": [
            {
                "question_text": "When does `model_rebuild(force=True)` need to run for lazily imported plugin models?",
                "why_it_matters": "Startup crashes occur if circular schema references stay unresolved before first request.",
                "priority": Priority.HIGH,
                "answer_text": "Call `model_rebuild(force=True)` right after plugin modules register in app lifespan.",
            },
            {
                "question_text": "Are TypeAdapter instances cached workspace-wide or per module in billing endpoints?",
                "why_it_matters": "Prevents p99 validation latency regressions during high-throughput batch imports.",
                "priority": Priority.MEDIUM,
                "answer_text": None,
            },
        ],
    },
    {
        "slug": "zulip",
        "source_name": "zulip/zulip",
        "case_title": "Zulip Server Architecture & Event Queue Handover",
        "case_description": (
            "Operational knowledge transfer for Zulip's Tornado real-time event queue, Redis pub/sub fanout, "
            "PostgreSQL full-text search migrations, and RabbitMQ deferred worker queues."
        ),
        "doc_filename": "zulip_event_queue_runbook.md",
        "doc_text": (
            "# Zulip Real-Time & Worker Operations Runbook\n\n"
            "## Tornado Event Queue Recovery\n"
            "Tornado holds long-lived client `event_queue` registrations in memory backed by Redis state. "
            "If Tornado workers restart unexpectedly, clients receive `BAD_EVENT_QUEUE_ID` and must perform "
            "a full `/register` state re-fetch.\n\n"
            "## Redis Pub/Sub Backpressure Mitigation\n"
            "When Redis pub/sub lag exceeds 5 seconds, inspect RabbitMQ worker queue depth via `manage.py check_rabbitmq` "
            "before restarting `zulip-tornado` workers."
        ),
        "records": [
            {
                "record_type": SourceRecordType.PR,
                "external_id": "31204",
                "title": "Bound Tornado event_queue idle GC during reconnect storms",
                "body": (
                    "Adjusts client queue garbage collection timeouts in zerver/tornado/event_queue.py so brief "
                    "mobile network drops do not force full /register state reloads."
                ),
                "state": "merged",
                "author": "arjun_patel",
                "url": "https://github.com/zulip/zulip/pull/31204",
                "days_ago": 12,
            },
            {
                "record_type": SourceRecordType.ISSUE,
                "external_id": "31411",
                "title": "ADR: Redis pub/sub reconnect fallback vs RabbitMQ queue draining",
                "body": (
                    "Decision: Keep Tornado event fanout on Redis pub/sub while isolating slow email/push jobs "
                    "in dedicated RabbitMQ worker queues so notification spikes cannot stall live chat."
                ),
                "state": "open",
                "author": "neha_gupta",
                "url": "https://github.com/zulip/zulip/issues/31411",
                "days_ago": 7,
            },
            {
                "record_type": SourceRecordType.PR,
                "external_id": "31502",
                "title": "Batch PostgreSQL search tsvector updates via RabbitMQ worker",
                "body": (
                    "Moves synchronous tsvector trigger updates out of message send transactions into "
                    "deferred RabbitMQ search index workers."
                ),
                "state": "merged",
                "author": "arjun_patel",
                "url": "https://github.com/zulip/zulip/pull/31502",
                "days_ago": 5,
            },
            {
                "record_type": SourceRecordType.COMMIT,
                "external_id": "f91032b19a01",
                "title": "ops: Add check_rabbitmq alerting threshold for missed_message queues",
                "body": (
                    "Documents RabbitMQ queue backlog alert thresholds and safe worker drain sequence during upgrades."
                ),
                "state": "committed",
                "author": "arjun_patel",
                "url": "https://github.com/zulip/zulip/commit/f91032b19a01",
                "days_ago": 3,
            },
        ],
        "packs": [
            {
                "name": "Tornado Event Queue & Real-Time Fanout",
                "component_area": "Real-Time Core",
                "description": "Tornado long-polling, event_queue GC thresholds, and Redis pub/sub failover.",
                "is_primary": True,
                "claims": [
                    {
                        "claim_type": ClaimType.OPERATIONAL_NOTE,
                        "title": "Tornado reconnect & BAD_EVENT_QUEUE_ID recovery flow",
                        "body_text": (
                            "Clients disconnected past the event queue idle GC window receive `BAD_EVENT_QUEUE_ID` "
                            "and recover state automatically via `/register`."
                        ),
                        "evidence_state": EvidenceState.SUPPORTED,
                        "review_state": ReviewState.ACCEPTED,
                        "priority": Priority.HIGH,
                        "rec_ext_id": "31204",
                        "locator": "PR #31204",
                    },
                    {
                        "claim_type": ClaimType.DECISION,
                        "title": "Decouple live Tornado pub/sub from RabbitMQ offline queues",
                        "body_text": (
                            "Live message delivery routes through Tornado + Redis pub/sub while emails, push "
                            "notifications, and `tsvector` updates run asynchronously in RabbitMQ workers."
                        ),
                        "evidence_state": EvidenceState.SUPPORTED,
                        "review_state": ReviewState.PENDING_REVIEW,
                        "priority": Priority.HIGH,
                        "rec_ext_id": "31411",
                        "locator": "Issue #31411",
                    },
                ],
            },
            {
                "name": "PostgreSQL Search & Background Workers",
                "component_area": "Database & Workers",
                "description": "Search index worker batching, RabbitMQ draining, and queue health monitoring.",
                "is_primary": False,
                "claims": [
                    {
                        "claim_type": ClaimType.WORK_ITEM,
                        "title": "Deferred tsvector search indexing in RabbitMQ worker",
                        "body_text": (
                            "Message sends enqueue deferred PostgreSQL `tsvector` indexing jobs rather than blocking "
                            "foreground DB transactions."
                        ),
                        "evidence_state": EvidenceState.SUPPORTED,
                        "review_state": ReviewState.PENDING_REVIEW,
                        "priority": Priority.MEDIUM,
                        "rec_ext_id": "31502",
                        "locator": "PR #31502",
                    },
                    {
                        "claim_type": ClaimType.RISK,
                        "title": "Verify Redis pub/sub shard failover runbook under production load",
                        "body_text": (
                            "Failover timing during Sentinel promotion lacks load-test benchmarks under peak realm "
                            "fanout concurrency."
                        ),
                        "evidence_state": EvidenceState.UNKNOWN,
                        "review_state": ReviewState.PENDING_REVIEW,
                        "priority": Priority.MEDIUM,
                        "rec_ext_id": "doc-zulip",
                        "locator": "Section 2: Redis Pub/Sub Backpressure Mitigation",
                    },
                ],
            },
        ],
        "questions": [
            {
                "question_text": "How does the Tornado event queue handle backpressure during mobile reconnect storms?",
                "why_it_matters": "Avoids cascading /register storms during brief regional network brownouts.",
                "priority": Priority.HIGH,
                "answer_text": "Idle event_queue GC window keeps queues buffered briefly per PR #31204 before issuing BAD_EVENT_QUEUE_ID.",
            },
            {
                "question_text": "What is the fallback procedure if the Redis pub/sub connection drops mid-shift?",
                "why_it_matters": "Ensures zero lost real-time chat events when Redis restarts.",
                "priority": Priority.MEDIUM,
                "answer_text": None,
            },
        ],
    },
]


def seed_project_repo_fixtures(db: Session) -> dict[str, int]:
    """Idempotently populate Pydantic and Zulip showcase datasets without touching existing cases."""
    now = datetime.now(timezone.utc)
    users = {u.email: u for u in db.query(User).all()}
    maya = users.get("maya.sharma@example.test")
    kabir = users.get("kabir.singh@example.test")
    arjun = users.get("arjun.patel@example.test")
    aisha = users.get("aisha.khan@example.test")
    if not (maya and kabir and arjun and aisha):
        return {"projects_seeded": 0}

    projects_seeded = 0

    for spec in _PROJECT_SPECS:
        project = db.query(Project).filter(Project.slug == spec["slug"]).first()
        if not project:
            continue

        source = (
            db.query(ConnectedSource)
            .filter(
                ConnectedSource.project_id == project.id,
                ConnectedSource.name == spec["source_name"],
            )
            .first()
        )
        if not source:
            owner, repo = spec["source_name"].split("/", 1)
            source = ConnectedSource(
                project_id=project.id,
                source_type=SourceType.GITHUB_REPO,
                name=spec["source_name"],
                external_id=spec["source_name"],
                connection_status=ConnectionStatus.ACTIVE,
                config={"owner": owner, "repo": repo},
                connected_by_id=maya.id,
            )
            db.add(source)
            db.flush()

        # Ensure SyncRun telemetry exists so Source Inventory displays completed sync history
        has_sync = db.query(SyncRun).filter(SyncRun.source_id == source.id).first()
        if not has_sync:
            db.add(
                SyncRun(
                    source_id=source.id,
                    status=SyncRunStatus.COMPLETED,
                    started_at=now - timedelta(minutes=2),
                    completed_at=now - timedelta(minutes=1),
                    records_fetched=len(spec["records"]),
                    records_created=len(spec["records"]),
                    records_updated=0,
                )
            )

        # Ensure grounded Document row exists
        doc_bytes = spec["doc_text"].encode("utf-8")
        doc_hash = hashlib.sha256(doc_bytes).hexdigest()
        doc = (
            db.query(Document)
            .filter(Document.project_id == project.id, Document.original_filename == spec["doc_filename"])
            .first()
        )
        sections = build_document_section_chunks(None, spec["doc_text"])
        if not doc:
            doc = Document(
                project_id=project.id,
                filename=f"seed_{spec['slug']}_{spec['doc_filename']}",
                original_filename=spec["doc_filename"],
                mime_type="text/markdown",
                file_size=len(doc_bytes),
                storage_path=f"{project.id}/{spec['doc_filename']}",
                file_hash=doc_hash,
                processing_status=ProcessingStatus.COMPLETED,
                sensitivity=Sensitivity.GENERAL,
                extracted_text=spec["doc_text"],
                page_count=1,
                section_count=len(sections),
                extraction_metadata={"sections": sections, "section_count": len(sections)},
                uploaded_by_id=maya.id,
            )
            db.add(doc)
            db.flush()

        # Upsert grounded SourceRecords cleanly by (connected_source_id, record_type, external_id)
        records_by_ext: dict[str, SourceRecord] = {}
        for r_spec in spec["records"]:
            rec = (
                db.query(SourceRecord)
                .filter(
                    SourceRecord.connected_source_id == source.id,
                    SourceRecord.record_type == r_spec["record_type"],
                    SourceRecord.external_id == r_spec["external_id"],
                )
                .first()
            )
            if not rec:
                ts = now - timedelta(days=r_spec["days_ago"])
                rec = SourceRecord(
                    connected_source_id=source.id,
                    source_type=SourceType.GITHUB_REPO.value,
                    record_type=r_spec["record_type"],
                    external_id=r_spec["external_id"],
                    title=r_spec["title"],
                    body=r_spec["body"],
                    state=r_spec["state"],
                    author_external_id=r_spec["author"],
                    author_name=r_spec["author"],
                    url=r_spec["url"],
                    sensitivity=Sensitivity.GENERAL,
                    processing_status=ProcessingStatus.COMPLETED,
                    external_created_at=ts,
                    external_updated_at=ts,
                )
                db.add(rec)
                db.flush()
            records_by_ext[r_spec["external_id"]] = rec

        # Bridge document runbook SourceRecord
        doc_ext_id = f"doc-{spec['slug']}"
        doc_src = (
            db.query(SourceRecord)
            .filter(
                SourceRecord.connected_source_id == source.id,
                SourceRecord.record_type == SourceRecordType.DOCUMENT_SECTION,
                SourceRecord.external_id == doc_ext_id,
            )
            .first()
        )
        if not doc_src:
            doc_src = SourceRecord(
                connected_source_id=source.id,
                source_type=SourceType.DOCUMENT_UPLOAD.value,
                record_type=SourceRecordType.DOCUMENT_SECTION,
                external_id=doc_ext_id,
                title=spec["doc_filename"],
                body=spec["doc_text"],
                author_name=maya.display_name,
                sensitivity=Sensitivity.GENERAL,
                processing_status=ProcessingStatus.COMPLETED,
                external_created_at=now - timedelta(days=2),
                external_updated_at=now - timedelta(days=2),
                metadata_json={"document_id": str(doc.id), "sections": sections},
            )
            db.add(doc_src)
            db.flush()
        records_by_ext[doc_ext_id] = doc_src

        # Only create flagship HandoverCase when this project has zero cases yet
        existing_cases_count = db.query(HandoverCase).filter(HandoverCase.project_id == project.id).count()
        if existing_cases_count > 0:
            continue

        case = HandoverCase(
            project_id=project.id,
            case_number=1,
            title=spec["case_title"],
            description=spec["case_description"],
            transition_type=TransitionType.PLANNED_DEPARTURE,
            status=CaseStatus.UNDER_REVIEW,
            sync_status=CaseSyncStatus.CURRENT,
            scope_start=now - timedelta(days=90),
            scope_end=now,
            created_by_id=maya.id,
        )
        db.add(case)
        db.flush()

        db.add(CaseSource(case_id=case.id, connected_source_id=source.id))
        for uid, role in [
            (maya.id, CaseParticipantRole.INITIATOR),
            (arjun.id, CaseParticipantRole.DEPARTING),
            (kabir.id, CaseParticipantRole.REVIEWER),
            (aisha.id, CaseParticipantRole.RECIPIENT),
        ]:
            db.add(CaseParticipant(case_id=case.id, user_id=uid, role=role))

        primary_pack: TransferPack | None = None
        for idx, p_spec in enumerate(spec["packs"]):
            pack = TransferPack(
                case_id=case.id,
                name=p_spec["name"],
                description=p_spec["description"],
                component_area=p_spec["component_area"],
                sort_order=idx,
                is_primary=p_spec["is_primary"],
                status=TransferPackStatus.UNDER_REVIEW,
                recorded_owner_id=arjun.id,
                suggested_successor_id=aisha.id,
            )
            db.add(pack)
            db.flush()
            if p_spec["is_primary"]:
                primary_pack = pack

            for c_spec in p_spec["claims"]:
                claim = Claim(
                    transfer_pack_id=pack.id,
                    claim_type=c_spec["claim_type"],
                    title=c_spec["title"],
                    body_text=c_spec["body_text"],
                    evidence_state=c_spec["evidence_state"],
                    freshness=Freshness.CURRENT,
                    review_state=c_spec["review_state"],
                    priority=c_spec["priority"],
                    reviewed_by=kabir.id if c_spec["review_state"] == ReviewState.ACCEPTED else None,
                    reviewed_at=now.isoformat() if c_spec["review_state"] == ReviewState.ACCEPTED else None,
                )
                db.add(claim)
                db.flush()

                src_rec = records_by_ext.get(c_spec["rec_ext_id"])
                if src_rec:
                    db.add(
                        ClaimEvidence(
                            claim_id=claim.id,
                            source_record_id=src_rec.id,
                            document_id=doc.id if c_spec["rec_ext_id"] == doc_ext_id else None,
                            excerpt=(src_rec.body or src_rec.title or "")[:240],
                            locator=c_spec["locator"],
                            evidence_type=EvidenceType.DIRECT_REFERENCE,
                            is_restricted=False,
                        )
                    )

        for q_spec in spec["questions"]:
            q = Question(
                case_id=case.id,
                transfer_pack_id=primary_pack.id if primary_pack else None,
                question_text=q_spec["question_text"],
                why_it_matters=q_spec["why_it_matters"],
                priority=q_spec["priority"],
                status=QuestionStatus.ANSWERED if q_spec["answer_text"] else QuestionStatus.OPEN,
                assigned_to_id=arjun.id,
                created_by_id=aisha.id,
            )
            db.add(q)
            db.flush()
            if q_spec["answer_text"]:
                db.add(
                    QuestionResponse(
                        question_id=q.id,
                        respondent_id=arjun.id,
                        response_text=q_spec["answer_text"],
                        review_state=QuestionResponseReviewState.PENDING_REVIEW,
                    )
                )

        projects_seeded += 1
        logger.info("Seeded handover fixture data for project '%s'", spec["slug"])

    db.commit()
    return {"projects_seeded": projects_seeded}
