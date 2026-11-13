"""Source refresh and staleness propagation service.

Phase 10 — Hardening & Demo.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.dependencies import get_user_context_capabilities
from app.db.enums import (
    CaseSyncStatus,
    Freshness,
    ReviewState,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
)
from app.modules.audit.service import create_audit_event
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import HandoverCase
from app.modules.ingestion.models import SourceEvent, SourceRecord
from app.modules.sources.models import ConnectedSource, SyncRun
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.sources.refresh")


def refresh_source(
    db: Session,
    source_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    simulate_modification: bool = False,
) -> dict:
    """Manually refresh a source, checking for content updates and propagating staleness."""
    source = db.query(ConnectedSource).filter(ConnectedSource.id == source_id).first()
    if not source:
        raise ValueError(f"Source {source_id} not found")

    # Fetch source records
    records = db.query(SourceRecord).filter(SourceRecord.connected_source_id == source.id).all()
    records_checked = len(records)
    records_changed = 0
    claims_stale_count = 0
    changed_record_ids = []

    # Determine baseline time for drift check (latest completed sync or source.updated_at)
    def _to_utc(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    last_sync = (
        db.query(SyncRun)
        .filter(SyncRun.source_id == source.id, SyncRun.completed_at.isnot(None))
        .order_by(SyncRun.completed_at.desc())
        .first()
    )
    baseline = _to_utc(last_sync.completed_at if last_sync else None) or _to_utc(source.updated_at) or _to_utc(source.created_at)

    # If simulate_modification is requested, or if any record has been modified after baseline
    now = datetime.now(timezone.utc)
    if simulate_modification and records:
        # Simulate an upstream modification on the first record
        target_rec = records[0]
        target_rec.external_updated_at = now
        target_rec.body = (target_rec.body or "") + "\n\n[Updated during manual source refresh]"
        db.flush()
        changed_record_ids.append(target_rec.id)
        records_changed += 1

    # Check if any records were modified externally after the baseline check
    if not changed_record_ids and baseline is not None:
        for r in records:
            upd = _to_utc(r.external_updated_at)
            if upd and upd > baseline:
                changed_record_ids.append(r.id)
                records_changed += 1

    # Propagate staleness to claims referencing changed records
    stale_claim_ids = set()
    cases_affected = set()

    if changed_record_ids:
        claim_evidences = (
            db.query(ClaimEvidence)
            .filter(ClaimEvidence.source_record_id.in_(changed_record_ids))
            .all()
        )

        for ce in claim_evidences:
            claim = db.query(Claim).filter(Claim.id == ce.claim_id).first()
            if not claim:
                continue

            # Determine freshness based on review state
            if claim.review_state in (ReviewState.ACCEPTED, ReviewState.EDITED_AND_ACCEPTED):
                claim.freshness = Freshness.CHANGED_SINCE_APPROVAL
            else:
                claim.freshness = Freshness.POTENTIALLY_STALE

            stale_claim_ids.add(claim.id)

            # Mark transfer pack and handover case
            pack = db.query(TransferPack).filter(TransferPack.id == claim.transfer_pack_id).first()
            if pack and pack.case_id:
                cases_affected.add(pack.case_id)

    claims_stale_count = len(stale_claim_ids)

    # Update sync_status for affected cases
    for case_id in cases_affected:
        case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
        if case:
            # Check if any claim in the case has CHANGED_SINCE_APPROVAL
            has_changed_approved = (
                db.query(Claim)
                .join(TransferPack, Claim.transfer_pack_id == TransferPack.id)
                .filter(
                    TransferPack.case_id == case.id,
                    Claim.freshness == Freshness.CHANGED_SINCE_APPROVAL,
                )
                .count()
            )
            if has_changed_approved > 0:
                case.sync_status = CaseSyncStatus.CHANGED_SINCE_APPROVAL
            else:
                case.sync_status = CaseSyncStatus.POTENTIALLY_STALE

    source.updated_at = now

    try:
        # Record audit event
        create_audit_event(
            db,
            actor_id=actor_id,
            action="source.refreshed",
            entity_type="connected_source",
            entity_id=source.id,
            details={
                "source_id": str(source.id),
                "records_checked": records_checked,
                "records_changed": records_changed,
                "claims_stale_count": claims_stale_count,
                "cases_affected_count": len(cases_affected),
            },
            summary=f"Checked local freshness for source {source.name}: {claims_stale_count} claims marked stale across {len(cases_affected)} cases (local timestamps only)",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "source_id": str(source.id),
        "source_name": source.name,
        "records_checked": records_checked,
        "records_changed": records_changed,
        "claims_marked_stale": claims_stale_count,
        "cases_affected": [str(c) for c in cases_affected],
        "is_local_only": True,
        "freshness_basis": "local_timestamps",
        "message": (
            f"Local freshness evaluation complete ({records_checked} imported records inspected locally; "
            f"no remote GitHub fetch performed). {claims_stale_count} claims updated."
        ),
    }


def refresh_case_sources(
    db: Session,
    case_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    simulate_modification: bool = False,
) -> dict:
    """Refresh all connected sources for the project associated with a handover case."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")

    sources = db.query(ConnectedSource).filter(ConnectedSource.project_id == case.project_id).all()
    results = []
    total_stale = 0

    for s in sources:
        res = refresh_source(
            db,
            s.id,
            actor_id=actor_id,
            simulate_modification=simulate_modification,
        )
        results.append(res)
        total_stale += res["claims_marked_stale"]

    db.refresh(case)

    try:
        create_audit_event(
            db,
            actor_id=actor_id,
            action="case.sources_refreshed",
            entity_type="handover_case",
            entity_id=case.id,
            details={
                "case_id": str(case.id),
                "sources_refreshed": len(sources),
                "total_stale_claims": total_stale,
                "new_sync_status": case.sync_status.value,
            },
            summary=f"Refreshed {len(sources)} sources for case {case.title} (sync status: {case.sync_status.value})",
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "case_id": str(case.id),
        "sync_status": case.sync_status.value,
        "sources_refreshed": len(sources),
        "total_claims_marked_stale": total_stale,
        "source_results": results,
    }


def _is_confirmed_pull_request_issue(issue_rec: SourceRecord) -> tuple[bool, str]:
    """Verify an ISSUE record truly represents a GitHub PR imported before PR filtering."""
    meta = issue_rec.metadata_json or {}
    url_lower = (issue_rec.url or "").lower()
    if meta.get("is_pull_request") is True:
        return True, "metadata.is_pull_request=True"
    if "/pull/" in url_lower:
        return True, "url_contains_/pull/"
    return False, "lacks_pull_request_metadata_or_url_marker"


def _require_cleanup_permission(
    db: Session,
    actor_id: uuid.UUID,
    *,
    target_project_ids: set[uuid.UUID],
    project_id: uuid.UUID | None,
) -> User:
    """Enforce that only a Project Lead or Workspace Owner may execute cleanup."""
    actor = db.query(User).filter(User.id == actor_id).first()
    if not actor or not actor.is_active:
        raise PermissionError("Active actor required for GitHub record deduplication")

    scope_projects = set(target_project_ids)
    if project_id is not None:
        scope_projects.add(project_id)

    if scope_projects:
        for pid in scope_projects:
            caps, _, _ = get_user_context_capabilities(db, actor, project_id=pid)
            if "source.cleanup" not in caps:
                raise PermissionError(
                    f"User lacks 'source.cleanup' capability on project {pid}; "
                    "restricted to Project Lead or Workspace Owner"
                )
    else:
        caps, _, _ = get_user_context_capabilities(db, actor)
        if "source.cleanup" not in caps:
            raise PermissionError(
                "User lacks 'source.cleanup' capability; restricted to Project Lead or Workspace Owner"
            )
    return actor


def analyze_duplicate_github_records(
    db: Session,
    *,
    source_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> dict:
    """Inspect connected sources for historical PR-as-ISSUE duplicates without mutating data."""
    source_query = db.query(ConnectedSource).filter(ConnectedSource.source_type == SourceType.GITHUB_REPO)
    if source_id is not None:
        source_query = source_query.filter(ConnectedSource.id == source_id)
    if project_id is not None:
        source_query = source_query.filter(ConnectedSource.project_id == project_id)
    sources = source_query.all()

    safe_duplicates: list[dict] = []
    ambiguous_records: list[dict] = []
    target_project_ids: set[uuid.UUID] = {s.project_id for s in sources}

    for src in sources:
        records = (
            db.query(SourceRecord)
            .filter(
                SourceRecord.connected_source_id == src.id,
                SourceRecord.record_type.in_([SourceRecordType.PR, SourceRecordType.ISSUE]),
            )
            .all()
        )
        by_ext: dict[str, dict[SourceRecordType, list[SourceRecord]]] = {}
        for rec in records:
            ext_key = (rec.external_id or "").strip()
            if not ext_key:
                continue
            by_ext.setdefault(ext_key, {}).setdefault(rec.record_type, []).append(rec)

        for ext_key, typed_map in sorted(by_ext.items()):
            prs = typed_map.get(SourceRecordType.PR, [])
            issues = typed_map.get(SourceRecordType.ISSUE, [])
            if not prs or not issues:
                continue

            if len(prs) > 1 or len(issues) > 1:
                ambiguous_records.append({
                    "source_id": str(src.id),
                    "source_name": src.name,
                    "external_id": ext_key,
                    "reason": "multiple_records_same_type_and_external_id",
                    "pr_ids": [str(p.id) for p in prs],
                    "issue_ids": [str(i.id) for i in issues],
                })
                continue

            canonical_pr = prs[0]
            issue_rec = issues[0]
            confirmed, marker = _is_confirmed_pull_request_issue(issue_rec)
            if not confirmed:
                ambiguous_records.append({
                    "source_id": str(src.id),
                    "source_name": src.name,
                    "external_id": ext_key,
                    "canonical_pr_id": str(canonical_pr.id),
                    "issue_id": str(issue_rec.id),
                    "issue_url": issue_rec.url,
                    "reason": marker,
                })
                continue

            ev_count = (
                db.query(ClaimEvidence)
                .filter(ClaimEvidence.source_record_id == issue_rec.id)
                .count()
            )
            events = (
                db.query(SourceEvent)
                .filter(SourceEvent.record_id == issue_rec.id)
                .all()
            )
            colliding_events = 0
            relinkable_events = 0
            for ev in events:
                if ev.external_id:
                    exists = (
                        db.query(SourceEvent.id)
                        .filter(
                            SourceEvent.record_id == canonical_pr.id,
                            SourceEvent.event_type == ev.event_type,
                            SourceEvent.external_id == ev.external_id,
                        )
                        .first()
                    )
                    if exists:
                        colliding_events += 1
                        continue
                relinkable_events += 1

            safe_duplicates.append({
                "source_id": str(src.id),
                "source_name": src.name,
                "project_id": str(src.project_id),
                "external_id": ext_key,
                "confirmation_marker": marker,
                "canonical_pr_id": str(canonical_pr.id),
                "duplicate_issue_id": str(issue_rec.id),
                "evidence_to_relink": ev_count,
                "events_to_relink": relinkable_events,
                "events_colliding": colliding_events,
            })

    return {
        "sources_scanned": len(sources),
        "target_project_ids": [str(pid) for pid in sorted(target_project_ids, key=str)],
        "safe_duplicate_count": len(safe_duplicates),
        "ambiguous_count": len(ambiguous_records),
        "safe_duplicates": safe_duplicates,
        "ambiguous_records": ambiguous_records,
    }


def cleanup_duplicate_github_records(
    db: Session,
    *,
    actor_id: uuid.UUID,
    source_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    dry_run: bool = True,
) -> dict:
    """Safely report or clean up duplicate PR-as-ISSUE GitHub records in an atomic transaction."""
    if source_id is not None:
        src_exists = db.query(ConnectedSource).filter(ConnectedSource.id == source_id).first()
        if not src_exists:
            raise ValueError(f"Source {source_id} not found")
        target_projects = {src_exists.project_id}
    else:
        source_q = db.query(ConnectedSource).filter(ConnectedSource.source_type == SourceType.GITHUB_REPO)
        if project_id is not None:
            source_q = source_q.filter(ConnectedSource.project_id == project_id)
        target_projects = {s.project_id for s in source_q.all()}

    _require_cleanup_permission(
        db,
        actor_id,
        target_project_ids=target_projects,
        project_id=project_id,
    )

    report = analyze_duplicate_github_records(
        db,
        source_id=source_id,
        project_id=project_id,
    )

    if dry_run:
        return {
            "dry_run": True,
            **report,
            "evidence_relinked": 0,
            "events_relinked": 0,
            "duplicate_events_removed": 0,
            "duplicates_deleted": 0,
        }

    evidence_relinked = 0
    events_relinked = 0
    duplicate_events_removed = 0
    duplicates_deleted = 0
    touched_sources: set[uuid.UUID] = set()

    savepoint = db.begin_nested()
    try:
        for item in report["safe_duplicates"]:
            pr_id = uuid.UUID(item["canonical_pr_id"])
            dup_id = uuid.UUID(item["duplicate_issue_id"])
            src_uuid = uuid.UUID(item["source_id"])

            canonical_pr = db.query(SourceRecord).filter(SourceRecord.id == pr_id).first()
            duplicate_issue = db.query(SourceRecord).filter(SourceRecord.id == dup_id).first()
            if not canonical_pr or not duplicate_issue:
                continue

            # 1. Re-link ClaimEvidence before deleting duplicate issue
            evidences = (
                db.query(ClaimEvidence)
                .filter(ClaimEvidence.source_record_id == duplicate_issue.id)
                .all()
            )
            for ce in evidences:
                ce.source_record_id = canonical_pr.id
                evidence_relinked += 1

            # 2. Re-link SourceEvent cleanly, resolving unique-identity collisions on canonical PR
            dup_events = (
                db.query(SourceEvent)
                .filter(SourceEvent.record_id == duplicate_issue.id)
                .all()
            )
            for ev in dup_events:
                collision = None
                if ev.external_id:
                    collision = (
                        db.query(SourceEvent.id)
                        .filter(
                            SourceEvent.record_id == canonical_pr.id,
                            SourceEvent.event_type == ev.event_type,
                            SourceEvent.external_id == ev.external_id,
                        )
                        .first()
                    )
                if collision:
                    db.delete(ev)
                    duplicate_events_removed += 1
                else:
                    ev.record_id = canonical_pr.id
                    events_relinked += 1

            # 3. Preserve missing non-empty text/timestamp conservatively
            if not canonical_pr.body and duplicate_issue.body:
                canonical_pr.body = duplicate_issue.body
            if canonical_pr.external_updated_at is None and duplicate_issue.external_updated_at is not None:
                canonical_pr.external_updated_at = duplicate_issue.external_updated_at

            db.flush()
            # Expire cached relationship collection so delete-orphan cascade never touches moved events
            db.expire(duplicate_issue, ["events"])
            db.delete(duplicate_issue)
            db.flush()
            duplicates_deleted += 1
            touched_sources.add(src_uuid)

        audit_entity_type = "connected_source" if source_id else "project"
        audit_entity_id = source_id or project_id or (next(iter(target_projects)) if target_projects else actor_id)
        create_audit_event(
            db,
            actor_id=actor_id,
            action="source.deduplicated",
            entity_type=audit_entity_type,
            entity_id=audit_entity_id,
            details={
                "source_id": str(source_id) if source_id else None,
                "project_id": str(project_id) if project_id else None,
                "duplicates_deleted": duplicates_deleted,
                "evidence_relinked": evidence_relinked,
                "events_relinked": events_relinked,
                "duplicate_events_removed": duplicate_events_removed,
                "ambiguous_skipped": report["ambiguous_count"],
                "touched_sources": [str(s) for s in sorted(touched_sources, key=str)],
            },
            summary=(
                f"GitHub deduplication cleanup: removed {duplicates_deleted} duplicate PR-as-ISSUE record(s), "
                f"re-linked {evidence_relinked} evidence item(s) and {events_relinked} event(s); "
                f"skipped {report['ambiguous_count']} ambiguous record(s)."
            ),
        )
        savepoint.commit()
        db.commit()
    except Exception:
        savepoint.rollback()
        db.rollback()
        raise

    return {
        "dry_run": False,
        **report,
        "evidence_relinked": evidence_relinked,
        "events_relinked": events_relinked,
        "duplicate_events_removed": duplicate_events_removed,
        "duplicates_deleted": duplicates_deleted,
    }
