"""Source refresh and staleness propagation service.

Phase 10 — Hardening & Demo.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.enums import (
    CaseSyncStatus,
    Freshness,
    ReviewState,
    TransferPackStatus,
)
from app.modules.audit.service import create_audit_event
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.sources.models import ConnectedSource, SyncRun
from app.modules.transfer_packs.models import Claim, TransferPack

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
        summary=f"Refreshed source {source.name}: {claims_stale_count} claims marked stale across {len(cases_affected)} cases",
    )
    db.commit()

    return {
        "source_id": str(source.id),
        "source_name": source.name,
        "records_checked": records_checked,
        "records_changed": records_changed,
        "claims_marked_stale": claims_stale_count,
        "cases_affected": [str(c) for c in cases_affected],
        "message": f"Source refresh complete. {claims_stale_count} claims updated.",
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

    return {
        "case_id": str(case.id),
        "sync_status": case.sync_status.value,
        "sources_refreshed": len(sources),
        "total_claims_marked_stale": total_stale,
        "source_results": results,
    }
