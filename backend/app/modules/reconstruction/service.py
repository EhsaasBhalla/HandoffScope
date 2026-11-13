"""Reconstruction service orchestrating source context assembly, LLM extraction, deterministic overrides, and claim persistence.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    CaseSyncStatus,
    ClaimType,
    ConnectionStatus,
    EvidenceState,
    EvidenceType,
    ExtractionRunStatus,
    Freshness,
    Priority,
    ProcessingStatus,
    QuestionStatus,
    ReviewState,
    SourceRecordType,
    SourceType,
    TransferPackStatus,
)
from app.integrations.documents import build_document_section_chunks
from app.integrations.llm.factory import get_llm_provider
from app.integrations.llm.prompts.extraction_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_extraction_context,
    build_user_prompt,
    select_relevant_source_records,
)
from app.integrations.llm.schemas.extraction import CandidateTransferPack, ExtractionResult
from app.integrations.llm.validators import validate_extraction_result
from app.modules.audit.service import create_audit_event
from app.modules.documents.models import Document
from app.modules.evidence.models import ClaimEvidence, ExtractionRun
from app.modules.handover_cases.models import CaseParticipant, CaseSource, HandoverCase
from app.modules.identity.models import IdentityMapping
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.questions.models import Question
from app.modules.reconstruction.schemas import ReconstructionTriggerResponse
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.reconstruction")


def _apply_deterministic_overrides(
    result: ExtractionResult,
    source_records_map: dict[str, SourceRecord],
) -> None:
    """Apply deterministic business rules that strictly override LLM interpretation.

    Rules:
    - Merged PR != deployed to production (override to INFERRED unless production logs exist).
    - Source record states (open/closed) supersede LLM assumptions.
    """
    for pack in result.transfer_packs:
        for item in getattr(pack, "work_items", []):
            for ref in item.evidence:
                sr = source_records_map.get(str(ref.source_record_id))
                if sr:
                    # If LLM marks 'deployed' or 'completed' based solely on a merged PR, enforce INFERRED
                    if sr.state == "merged" and "deploy" in item.title.lower():
                        item.evidence_state = EvidenceState.INFERRED


def run_extraction(
    db: Session,
    case_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> ReconstructionTriggerResponse:
    """Execute the full knowledge reconstruction pipeline for a handover case."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Handover case not found")

    if case.status in (CaseStatus.CANCELLED, CaseStatus.TRANSFERRED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reconstruct a case in terminal status '{case.status.value}'",
        )

    previous_status = case.status
    # Update case status to RECONSTRUCTING
    case.status = CaseStatus.RECONSTRUCTING
    db.commit()

    # 0. Bridge any completed project Documents that don't yet have SourceRecords
    completed_docs = (
        db.query(Document)
        .filter(
            Document.project_id == case.project_id,
            Document.processing_status == ProcessingStatus.COMPLETED,
        )
        .all()
    )
    if completed_docs:
        doc_source = (
            db.query(ConnectedSource)
            .filter(
                ConnectedSource.project_id == case.project_id,
                ConnectedSource.source_type == SourceType.DOCUMENT_UPLOAD,
            )
            .first()
        )
        if not doc_source:
            doc_source = ConnectedSource(
                project_id=case.project_id,
                source_type=SourceType.DOCUMENT_UPLOAD,
                name="Uploaded Documents",
                external_id=f"documents-{case.project_id}",
                connection_status=ConnectionStatus.ACTIVE,
                connected_by_id=actor_id or case.created_by_id,
            )
            db.add(doc_source)
            db.flush()

        uploader_ids = [doc.uploaded_by_id for doc in completed_docs if doc.uploaded_by_id]
        uploaders = (
            {u.id: u.display_name for u in db.query(User).filter(User.id.in_(uploader_ids)).all()}
            if uploader_ids
            else {}
        )
        existing_sr_map = {
            sr.external_id: sr
            for sr in db.query(SourceRecord)
            .filter(
                SourceRecord.connected_source_id == doc_source.id,
                SourceRecord.record_type == SourceRecordType.DOCUMENT_SECTION,
            )
            .all()
        }

        for doc in completed_docs:
            if not doc.extracted_text:
                continue
            existing_sr = existing_sr_map.get(str(doc.id))
            doc_meta = doc.extraction_metadata if isinstance(doc.extraction_metadata, dict) else {}
            sections = doc_meta.get("sections") or build_document_section_chunks(None, doc.extracted_text)
            uploader_name = uploaders.get(doc.uploaded_by_id)

            if not existing_sr:
                new_sr = SourceRecord(
                    connected_source_id=doc_source.id,
                    source_type=SourceType.DOCUMENT_UPLOAD.value,
                    record_type=SourceRecordType.DOCUMENT_SECTION,
                    external_id=str(doc.id),
                    title=doc.original_filename,
                    body=doc.extracted_text,
                    author_name=uploader_name,
                    sensitivity=doc.sensitivity,
                    processing_status=ProcessingStatus.COMPLETED,
                    external_created_at=doc.created_at,
                    external_updated_at=doc.updated_at or doc.created_at,
                    metadata_json={
                        "document_id": str(doc.id),
                        "mime_type": doc.mime_type,
                        "page_count": doc.page_count,
                        "section_count": len(sections),
                        "sections": sections,
                    },
                )
                db.add(new_sr)
                existing_sr_map[str(doc.id)] = new_sr
            elif not existing_sr.metadata_json or "sections" not in (existing_sr.metadata_json or {}):
                updated_meta = dict(existing_sr.metadata_json or {})
                updated_meta.update({
                    "document_id": str(doc.id),
                    "mime_type": doc.mime_type,
                    "sections": sections,
                    "section_count": len(sections),
                })
                existing_sr.metadata_json = updated_meta
        db.flush()

    # 1. Identify sources included in this case
    from app.modules.evidence.clearance import resolve_case_source_ids

    source_ids = resolve_case_source_ids(
        db,
        case_id=case_id,
        project_id=case.project_id,
    )

    if not source_ids:
        case.status = previous_status if previous_status != CaseStatus.RECONSTRUCTING else CaseStatus.DRAFT
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data sources connected to this case or project. Please connect a repository or upload documents first.",
        )

    # 2. Query source records within scope using canonical timestamp coalesce & inclusive end-of-day
    sr_query = db.query(SourceRecord).filter(SourceRecord.connected_source_id.in_(source_ids))
    canonical_ts = func.coalesce(SourceRecord.external_created_at, SourceRecord.created_at)
    if case.scope_start:
        start_dt = datetime.combine(case.scope_start, time.min, tzinfo=timezone.utc)
        sr_query = sr_query.filter(canonical_ts >= start_dt)
    if case.scope_end:
        end_dt = datetime.combine(case.scope_end, time.max, tzinfo=timezone.utc)
        sr_query = sr_query.filter(canonical_ts <= end_dt)

    # Fetch candidate pool (broad enough to retain older decisions/ADRs & docs before relevance ranking)
    candidate_records = sr_query.order_by(canonical_ts.desc(), SourceRecord.id.asc()).limit(500).all()

    if not candidate_records:
        case.status = CaseStatus.NEEDS_INPUT
        db.commit()
        return ReconstructionTriggerResponse(
            run_id=uuid.uuid4(),
            status="PARTIAL",
            packs_created=0,
            claims_created=0,
            evidence_linked=0,
            message="No source records found within the specified date scope.",
            provider_mode="none",
            model_used="none",
        )

    # Identify departing contributor names/handles/IDs for relevance weighting
    departing_ids: set[str] = set()
    departing_parts = (
        db.query(CaseParticipant)
        .filter(
            CaseParticipant.case_id == case_id,
            CaseParticipant.role == CaseParticipantRole.DEPARTING,
        )
        .all()
    )
    departing_user_uuids = [dp.user_id for dp in departing_parts if dp.user_id]
    if departing_user_uuids:
        for u in db.query(User).filter(User.id.in_(departing_user_uuids)).all():
            departing_ids.add(str(u.id))
            departing_ids.add(u.display_name)
            departing_ids.add(u.email.split("@")[0])
        for m in (
            db.query(IdentityMapping)
            .filter(
                IdentityMapping.project_id == case.project_id,
                IdentityMapping.mapped_user_id.in_(departing_user_uuids),
            )
            .all()
        ):
            if m.external_username:
                departing_ids.add(m.external_username)
            if m.external_id:
                departing_ids.add(m.external_id)

    # Deterministically select relevant, token-bounded, deduplicated context records
    records, context_stats = select_relevant_source_records(
        candidate_records,
        case_title=case.title,
        case_description=case.description or "",
        departing_identifiers=departing_ids,
    )

    # Maps for strict grounding validation (ONLY selected records placed into prompt context)
    source_records_map = {str(r.id): r for r in records}
    input_source_ids = set(source_records_map.keys())

    # 3. Assemble bounded, injection-safe context
    project = db.query(Project).filter(Project.id == case.project_id).first()
    context_str = build_extraction_context(records)
    user_prompt = build_user_prompt(
        context_str,
        project_name=project.name if project else "Project",
        case_title=case.title,
    )

    # 4. Request structured extraction via LLM Provider (recover case status cleanly on failure)
    provider = get_llm_provider()
    run_id = uuid.uuid4()
    try:
        extraction_result, usage_meta = provider.extract_structured(
            SYSTEM_PROMPT,
            user_prompt,
            ExtractionResult,
        )
        raw_output_snapshot = extraction_result.model_copy(deep=True).model_dump()
    except Exception as exc:
        logger.exception("LLM extraction failed for case %s: %s", case_id, exc)
        db.rollback()
        case_obj = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
        if case_obj:
            case_obj.status = previous_status if previous_status != CaseStatus.RECONSTRUCTING else CaseStatus.DRAFT
        db.add(
            ExtractionRun(
                id=run_id,
                case_id=case_id,
                model_name=provider.get_model_name(),
                model_version="1.0",
                prompt_template_version=PROMPT_VERSION,
                input_source_record_ids=list(input_source_ids),
                status=ExtractionRunStatus.FAILED,
                error_message=str(exc)[:1000],
            )
        )
        db.commit()
        raise HTTPException(status_code=500, detail=f"Knowledge extraction failed: {exc}")

    # 5. Deterministic validation pipeline
    validated_result, validation_errors = validate_extraction_result(
        extraction_result,
        input_source_ids,
        source_records_map,
    )

    # 6. Apply deterministic state overrides
    _apply_deterministic_overrides(validated_result, source_records_map)

    actual_model_used = usage_meta.get("model_used") or provider.get_model_name()
    provider_mode = usage_meta.get("provider_mode") or (
        "mock" if "mock" in actual_model_used.lower() else "live"
    )
    fallback_used = bool(usage_meta.get("fallback_used", False))
    fallback_reason = usage_meta.get("fallback_reason")

    validated_payload = validated_result.model_dump()
    validated_payload["_provider_meta"] = {
        "provider_mode": provider_mode,
        "model_used": actual_model_used,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "context_stats": context_stats,
        "validation_errors_count": len(validation_errors),
    }

    # 7. Persist ExtractionRun
    extraction_run = ExtractionRun(
        id=run_id,
        case_id=case_id,
        model_name=actual_model_used,
        model_version="1.0",
        prompt_template_version=PROMPT_VERSION,
        input_source_record_ids=list(input_source_ids),
        token_usage_input=usage_meta.get("input_tokens"),
        token_usage_output=usage_meta.get("output_tokens"),
        latency_ms=usage_meta.get("latency_ms"),
        status=ExtractionRunStatus.COMPLETED,
        raw_output_json=raw_output_snapshot,
        validated_output_json=validated_payload,
    )
    db.add(extraction_run)
    db.flush()

    # 8. Persist Transfer Packs, Claims, and Grounded Evidence
    packs_created = 0
    claims_created = 0
    evidence_linked = 0

    packs_to_persist = list(validated_result.transfer_packs)
    if validated_result.unassigned_items or validated_result.cross_cutting_risks or validated_result.cross_cutting_gaps:
        packs_to_persist.append(
            CandidateTransferPack(
                name="Cross-Cutting Risks & Operational Gaps",
                description="Cross-cutting risks, unassigned items, and identified gaps across components.",
                component_area="Cross-Cutting",
                work_items=validated_result.unassigned_items,
                risks=validated_result.cross_cutting_risks,
                knowledge_gaps=validated_result.cross_cutting_gaps,
            )
        )

    # Bulk query existing question texts for case once to prevent N+1 queries
    existing_q_texts = {
        row[0]
        for row in db.query(Question.question_text)
        .filter(Question.case_id == case_id)
        .all()
    }

    for sort_idx, ctp in enumerate(packs_to_persist):
        pack = (
            db.query(TransferPack)
            .filter(TransferPack.case_id == case_id, TransferPack.name == ctp.name)
            .first()
        )
        if not pack:
            pack = TransferPack(
                id=uuid.uuid4(),
                case_id=case_id,
                name=ctp.name,
                description=ctp.description,
                component_area=ctp.component_area,
                status=TransferPackStatus.DRAFT,
                sort_order=sort_idx,
            )
            db.add(pack)
            db.flush()
            packs_created += 1

        # Bulk query existing claims in this pack once to eliminate N+1 roundtrips
        existing_claims_map = {
            (c.title, c.claim_type): c
            for c in db.query(Claim).filter(Claim.transfer_pack_id == pack.id).all()
        }

        # Helper to persist a list of items as claims
        def _save_claims(items: list[Any], claim_type: ClaimType):
            nonlocal claims_created, evidence_linked
            for it in items:
                # Check for existing duplicate title in pack via in-memory index
                existing = existing_claims_map.get((it.title, claim_type))
                if existing:
                    # Refresh staleness marker on regeneration
                    if existing.freshness in (Freshness.POTENTIALLY_STALE, Freshness.CHANGED_SINCE_APPROVAL):
                        existing.freshness = Freshness.CURRENT
                    continue

                ev_state_val = getattr(it, "evidence_state", EvidenceState.SUPPORTED)
                if hasattr(ev_state_val, "value"):
                    ev_state_val = ev_state_val.value

                claim = Claim(
                    id=uuid.uuid4(),
                    transfer_pack_id=pack.id,
                    claim_type=claim_type,
                    title=it.title,
                    body_text=getattr(it, "description", None),
                    evidence_state=EvidenceState(ev_state_val) if ev_state_val in EvidenceState.__members__ else EvidenceState.SUPPORTED,
                    freshness=Freshness.CURRENT,
                    review_state=ReviewState.PENDING_REVIEW,
                    priority=Priority.HIGH if getattr(it, "priority", None) in ["HIGH", "CRITICAL"] else Priority.MEDIUM,
                    extraction_run_id=str(run_id),
                )
                db.add(claim)
                existing_claims_map[(claim.title, claim.claim_type)] = claim
                claims_created += 1

                # Link evidence (strictly discard hallucinated citations not present in DB)
                for ev_ref in getattr(it, "evidence", []):
                    sr_id_str = str(getattr(ev_ref, "source_record_id", "")).strip()
                    if not sr_id_str or sr_id_str not in source_records_map:
                        continue
                    try:
                        sr_id = uuid.UUID(sr_id_str)
                    except (ValueError, TypeError):
                        continue

                    claim_ev = ClaimEvidence(
                        id=uuid.uuid4(),
                        claim_id=claim.id,
                        source_record_id=sr_id,
                        excerpt=ev_ref.excerpt,
                        locator=ev_ref.locator,
                        evidence_type=EvidenceType.DIRECT_REFERENCE,
                        is_restricted=getattr(ev_ref, "is_restricted", False),
                    )
                    db.add(claim_ev)
                    evidence_linked += 1

        _save_claims(ctp.work_items, ClaimType.WORK_ITEM)
        _save_claims(ctp.decisions, ClaimType.DECISION)
        _save_claims(ctp.dependencies, ClaimType.DEPENDENCY)
        _save_claims(ctp.risks, ClaimType.RISK)
        _save_claims(ctp.operational_notes, ClaimType.OPERATIONAL_NOTE)
        _save_claims(ctp.knowledge_gaps, ClaimType.KNOWLEDGE_GAP)
        _save_claims(ctp.next_actions, ClaimType.NEXT_ACTION)

        # Flush once per pack instead of after every claim
        db.flush()

        # Queue question suggestions using in-memory set
        for q_sug in ctp.question_suggestions:
            if q_sug.question_text not in existing_q_texts:
                raw_prio = getattr(q_sug, "priority", "MEDIUM")
                prio = Priority(raw_prio) if raw_prio in Priority.__members__ else Priority.MEDIUM
                new_q = Question(
                    id=uuid.uuid4(),
                    case_id=case_id,
                    transfer_pack_id=pack.id,
                    question_text=q_sug.question_text,
                    why_it_matters=q_sug.why_it_matters,
                    priority=prio,
                    status=QuestionStatus.DRAFT,
                    created_by_id=actor_id or case.created_by_id,
                )
                db.add(new_q)
                existing_q_texts.add(q_sug.question_text)

        db.flush()

    # 9. Update case status & sync status cleanly
    if previous_status in (CaseStatus.DRAFT, CaseStatus.CONNECTING, CaseStatus.INGESTING, CaseStatus.RECONSTRUCTING, CaseStatus.NEEDS_INPUT):
        case.status = CaseStatus.NEEDS_INPUT
    else:
        case.status = previous_status
    case.sync_status = CaseSyncStatus.CURRENT

    # 10. Audit log
    create_audit_event(
        db,
        actor_id=actor_id,
        action="RECONSTRUCTION_COMPLETED",
        entity_type="handover_case",
        entity_id=case_id,
        details={
            "run_id": str(run_id),
            "packs_created": packs_created,
            "claims_created": claims_created,
            "evidence_linked": evidence_linked,
            "model_used": actual_model_used,
            "provider_mode": provider_mode,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "context_stats": context_stats,
        },
        summary=(
            f"Reconstructed knowledge ({provider_mode}, model={actual_model_used}): "
            f"{packs_created} Transfer Packs, {claims_created} claims with {evidence_linked} evidence references."
        ),
    )

    db.commit()

    mode_note = ""
    if fallback_used:
        mode_note = f" [MOCK FALLBACK active ({fallback_reason}) — not generated by live AI]"
    elif provider_mode == "mock":
        mode_note = " [Offline Mock Mode — not generated by live AI]"

    return ReconstructionTriggerResponse(
        run_id=run_id,
        status="COMPLETED",
        packs_created=packs_created,
        claims_created=claims_created,
        evidence_linked=evidence_linked,
        message=f"Reconstruction complete: {packs_created} Transfer Packs generated with {claims_created} grounded claims.{mode_note}",
        provider_mode=provider_mode,
        model_used=actual_model_used,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        context_stats=context_stats,
    )
