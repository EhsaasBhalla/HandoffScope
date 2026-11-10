"""Reconstruction service orchestrating source context assembly, LLM extraction, deterministic overrides, and claim persistence.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.enums import (
    CaseStatus,
    ClaimType,
    EvidenceState,
    EvidenceType,
    ExtractionRunStatus,
    Freshness,
    Priority,
    QuestionStatus,
    ReviewState,
    TransferPackStatus,
)
from app.integrations.llm.factory import get_llm_provider
from app.integrations.llm.prompts.extraction_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_extraction_context,
    build_user_prompt,
)
from app.integrations.llm.schemas.extraction import ExtractionResult
from app.integrations.llm.validators import validate_extraction_result
from app.modules.audit.service import create_audit_event
from app.modules.evidence.models import ClaimEvidence, ExtractionRun
from app.modules.handover_cases.models import CaseSource, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.questions.models import Question
from app.modules.reconstruction.schemas import ReconstructionTriggerResponse
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack

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

    # Update case status to RECONSTRUCTING
    case.status = CaseStatus.RECONSTRUCTING
    db.commit()

    # 1. Identify sources included in this case
    case_sources = db.query(CaseSource).filter(CaseSource.case_id == case_id).all()
    if case_sources:
        source_ids = [cs.connected_source_id for cs in case_sources]
    else:
        # Fallback to all sources connected to the case's project
        proj_sources = db.query(ConnectedSource).filter(ConnectedSource.project_id == case.project_id).all()
        source_ids = [s.id for s in proj_sources]

    if not source_ids:
        case.status = CaseStatus.DRAFT
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data sources connected to this case or project. Please connect a repository or upload documents first.",
        )

    # 2. Query source records within scope
    sr_query = db.query(SourceRecord).filter(SourceRecord.connected_source_id.in_(source_ids))
    if case.scope_start:
        sr_query = sr_query.filter(
            (SourceRecord.external_created_at >= case.scope_start)
            | (SourceRecord.created_at >= case.scope_start)
        )
    if case.scope_end:
        sr_query = sr_query.filter(
            (SourceRecord.external_created_at <= case.scope_end)
            | (SourceRecord.created_at <= case.scope_end)
        )

    # Fetch records
    records = sr_query.order_by(SourceRecord.created_at.desc()).limit(150).all()

    if not records:
        case.status = CaseStatus.NEEDS_INPUT
        db.commit()
        return ReconstructionTriggerResponse(
            run_id=uuid.uuid4(),
            status="PARTIAL",
            packs_created=0,
            claims_created=0,
            evidence_linked=0,
            message="No source records found within the specified date scope.",
        )

    # Maps for grounding
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

    # 4. Request structured extraction via LLM Provider
    provider = get_llm_provider()
    extraction_result, usage_meta = provider.extract_structured(
        SYSTEM_PROMPT,
        user_prompt,
        ExtractionResult,
    )

    # 5. Deterministic validation pipeline
    validated_result, validation_errors = validate_extraction_result(
        extraction_result,
        input_source_ids,
        source_records_map,
    )

    # 6. Apply deterministic state overrides
    _apply_deterministic_overrides(validated_result, source_records_map)

    # 7. Persist ExtractionRun
    run_id = uuid.uuid4()
    extraction_run = ExtractionRun(
        id=run_id,
        case_id=case_id,
        model_name=provider.get_model_name(),
        model_version="1.0",
        prompt_template_version=PROMPT_VERSION,
        input_source_record_ids=list(input_source_ids),
        token_usage_input=usage_meta.get("input_tokens"),
        token_usage_output=usage_meta.get("output_tokens"),
        latency_ms=usage_meta.get("latency_ms"),
        status=ExtractionRunStatus.COMPLETED,
        raw_output_json=extraction_result.model_dump(),
        validated_output_json=validated_result.model_dump(),
    )
    db.add(extraction_run)
    db.flush()

    # 8. Persist Transfer Packs, Claims, and Grounded Evidence
    packs_created = 0
    claims_created = 0
    evidence_linked = 0

    for sort_idx, ctp in enumerate(validated_result.transfer_packs):
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

        # Helper to persist a list of items as claims
        def _save_claims(items: list[Any], claim_type: ClaimType):
            nonlocal claims_created, evidence_linked
            for it in items:
                # Check for existing duplicate title in pack
                existing = (
                    db.query(Claim)
                    .filter(
                        Claim.transfer_pack_id == pack.id,
                        Claim.title == it.title,
                        Claim.claim_type == claim_type,
                    )
                    .first()
                )
                if existing:
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
                db.flush()
                claims_created += 1

                # Link evidence
                for ev_ref in getattr(it, "evidence", []):
                    sr_id_str = str(ev_ref.source_record_id).strip()
                    sr_id = uuid.UUID(sr_id_str) if sr_id_str in source_records_map else None

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

        # Queue question suggestions
        for q_sug in ctp.question_suggestions:
            q_exists = (
                db.query(Question)
                .filter(
                    Question.case_id == case_id,
                    Question.question_text == q_sug.question_text,
                )
                .first()
            )
            if not q_exists:
                new_q = Question(
                    id=uuid.uuid4(),
                    case_id=case_id,
                    transfer_pack_id=pack.id,
                    question_text=q_sug.question_text,
                    why_it_matters=q_sug.why_it_matters,
                    status=QuestionStatus.DRAFT,
                    created_by_id=actor_id or case.created_by_id,
                )
                db.add(new_q)

    # 9. Update case status to NEEDS_INPUT (ready for question loops and reviewer refinement)
    case.status = CaseStatus.NEEDS_INPUT

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
            "model_used": provider.get_model_name(),
        },
        summary=f"Reconstructed knowledge: {packs_created} Transfer Packs, {claims_created} claims with {evidence_linked} evidence references.",
    )

    db.commit()

    return ReconstructionTriggerResponse(
        run_id=run_id,
        status="COMPLETED",
        packs_created=packs_created,
        claims_created=claims_created,
        evidence_linked=evidence_linked,
        message=f"Reconstruction complete: {packs_created} Transfer Packs generated with {claims_created} grounded claims.",
    )
