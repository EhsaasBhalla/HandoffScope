"""Service layer for Questions and Responses.

Phase 7 — Targeted Questions & Knowledge Gaps.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_user_context_capabilities
from app.core.events import publish_case_event
from app.core.exceptions import ConflictError, ForbiddenError
from app.db.enums import (
    CaseParticipantRole,
    CaseStatus,
    ClaimType,
    EvidenceState,
    EvidenceType,
    Freshness,
    Priority,
    ProjectRole,
    QuestionResponseReviewState,
    QuestionStatus,
    ReviewState,
    Sensitivity,
    TransferPackStatus,
    WorkspaceRole,
)
from app.integrations.llm.factory import get_llm_provider
from app.integrations.llm.prompts.question_answering_v1 import (
    QA_PROMPT_VERSION,
    QA_SYSTEM_PROMPT,
    build_qa_user_prompt,
    select_qa_evidence_context,
)
from app.integrations.llm.schemas.qa import QuestionAnswerResult
from app.modules.audit.service import create_audit_event
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import CaseParticipant, CaseSource, HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.questions.models import Question, QuestionResponse
from app.modules.questions.schemas import (
    QuestionCreate,
    QuestionOut,
    QuestionResponseOut,
    QuestionUpdate,
)
from app.modules.sources.models import ConnectedSource
from app.modules.transfer_packs.models import Claim, TransferPack
from app.modules.workspaces.models import User

logger = logging.getLogger("handoffscope.questions")

# Prevent duplicate concurrent AI answer generations on the same question
_ACTIVE_AI_GEN_LOCK = threading.Lock()
_ACTIVE_AI_QUESTIONS: set[uuid.UUID] = set()


def _to_question_out(q: Question, promotion_result: dict[str, Any] | None = None) -> QuestionOut:
    responses = [
        QuestionResponseOut(
            id=r.id,
            question_id=r.question_id,
            respondent_id=r.respondent_id,
            respondent_name=(
                r.respondent.display_name
                if r.respondent
                else ("HandoffScope AI (Draft)" if getattr(r, "is_ai_generated", False) else None)
            ),
            response_text=r.response_text,
            review_state=r.review_state.value if hasattr(r.review_state, "value") else str(r.review_state),
            reviewed_by_id=r.reviewed_by_id,
            reviewed_by_name=r.reviewer.display_name if r.reviewer else None,
            reviewed_at=r.reviewed_at,
            review_notes=r.review_notes,
            is_ai_generated=bool(getattr(r, "is_ai_generated", False)),
            ai_provider=getattr(r, "ai_provider", None),
            ai_model=getattr(r, "ai_model", None),
            answer_status=getattr(r, "answer_status", None),
            evidence_references=list(getattr(r, "evidence_json", None) or []),
            limitations=getattr(r, "limitations", None),
            conflicts=list(getattr(r, "conflicts_json", None) or []),
            provenance=getattr(r, "provenance_json", None),
            created_at=r.created_at.isoformat(),
        )
        for r in q.responses
    ]
    return QuestionOut(
        id=q.id,
        case_id=q.case_id,
        case_number=q.case.case_number if q.case else None,
        case_title=q.case.title if q.case else None,
        transfer_pack_id=q.transfer_pack_id,
        transfer_pack_name=q.transfer_pack.name if q.transfer_pack else None,
        claim_id=q.claim_id,
        claim_title=q.claim.title if getattr(q, "claim", None) else None,
        question_text=q.question_text,
        why_it_matters=q.why_it_matters,
        assigned_to_id=q.assigned_to_id,
        assigned_to_name=q.assigned_to.display_name if q.assigned_to else None,
        priority=q.priority.value if hasattr(q.priority, "value") else str(q.priority),
        status=q.status.value if hasattr(q.status, "value") else str(q.status),
        due_date=q.due_date,
        created_by_id=q.created_by_id,
        created_by_name=q.created_by.display_name if q.created_by else None,
        created_at=q.created_at.isoformat(),
        responses=responses,
        promotion_result=promotion_result,
    )


def list_questions(
    db: Session,
    *,
    case_id: uuid.UUID | None = None,
    status: str | None = None,
    assigned_to_id: uuid.UUID | None = None,
) -> list[QuestionOut]:
    """Query questions with optional case, status, or assignee filters."""
    query = (
        db.query(Question)
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.claim),
            joinedload(Question.assigned_to),
            joinedload(Question.created_by),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .order_by(Question.created_at.desc())
    )

    if case_id:
        query = query.filter(Question.case_id == case_id)
    if assigned_to_id:
        query = query.filter(Question.assigned_to_id == assigned_to_id)
    if status and status.upper() != "ALL":
        try:
            enum_status = QuestionStatus(status.upper())
            query = query.filter(Question.status == enum_status)
        except ValueError:
            pass

    questions = query.all()
    return [_to_question_out(q) for q in questions]


def get_question(db: Session, *, question_id: uuid.UUID) -> QuestionOut:
    """Get a single question by ID with loaded relationships."""
    question = (
        db.query(Question)
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.claim),
            joinedload(Question.assigned_to),
            joinedload(Question.created_by),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .filter(Question.id == question_id)
        .first()
    )
    if not question:
        raise ValueError("Question not found")
    return _to_question_out(question)


def create_question(
    db: Session,
    *,
    user_id: uuid.UUID,
    data: QuestionCreate,
) -> QuestionOut:
    """Create a new question on a handover case."""
    priority = Priority.MEDIUM
    if data.priority:
        try:
            priority = Priority(data.priority.upper())
        except ValueError:
            pass

    question = Question(
        case_id=data.case_id,
        question_text=data.question_text,
        why_it_matters=data.why_it_matters,
        transfer_pack_id=data.transfer_pack_id,
        claim_id=data.claim_id,
        assigned_to_id=data.assigned_to_id,
        priority=priority,
        status=QuestionStatus.OPEN,
        due_date=data.due_date,
        created_by_id=user_id,
    )
    db.add(question)
    try:
        db.flush()

        create_audit_event(
            db,
            actor_id=user_id,
            action="question.created",
            entity_type="question",
            entity_id=question.id,
            details={"case_id": str(data.case_id), "question": data.question_text[:100]},
            summary=f"Created question: {data.question_text[:80]}",
        )
        db.commit()
        db.refresh(question)
    except Exception:
        db.rollback()
        raise
    publish_case_event(
        case_id=question.case_id,
        event_type="question.answered",
        entity_id=str(question.id),
    )
    return _to_question_out(question)


VALID_QUESTION_TRANSITIONS: dict[QuestionStatus, set[QuestionStatus]] = {
    QuestionStatus.DRAFT: {QuestionStatus.OPEN, QuestionStatus.CANCELLED, QuestionStatus.DISMISSED},
    QuestionStatus.OPEN: {QuestionStatus.ANSWERED, QuestionStatus.DISMISSED, QuestionStatus.CANCELLED},
    QuestionStatus.ANSWERED: {QuestionStatus.PENDING_REVIEW, QuestionStatus.OPEN, QuestionStatus.RESOLVED, QuestionStatus.DISMISSED},
    QuestionStatus.PENDING_REVIEW: {QuestionStatus.RESOLVED, QuestionStatus.OPEN, QuestionStatus.DISMISSED},
    QuestionStatus.RESOLVED: {QuestionStatus.OPEN},
    QuestionStatus.DISMISSED: {QuestionStatus.OPEN},
    QuestionStatus.CANCELLED: {QuestionStatus.OPEN, QuestionStatus.DRAFT},
}


def update_question(
    db: Session,
    *,
    question_id: uuid.UUID,
    user_id: uuid.UUID,
    data: QuestionUpdate,
) -> QuestionOut:
    """Update question fields or transition question status."""
    q_query = db.query(Question).filter(Question.id == question_id)
    try:
        if db.bind and db.bind.dialect.name != "sqlite":
            q_query = q_query.with_for_update()
    except Exception:
        pass
    question = (
        q_query
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.claim),
            joinedload(Question.assigned_to),
            joinedload(Question.created_by),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .first()
    )
    if not question:
        raise ValueError("Question not found")

    changed_fields = []

    if data.question_text is not None and data.question_text != question.question_text:
        question.question_text = data.question_text
        changed_fields.append("question_text")

    if data.why_it_matters is not None and data.why_it_matters != question.why_it_matters:
        question.why_it_matters = data.why_it_matters
        changed_fields.append("why_it_matters")

    if data.transfer_pack_id is not None and data.transfer_pack_id != question.transfer_pack_id:
        question.transfer_pack_id = data.transfer_pack_id
        changed_fields.append("transfer_pack_id")

    if data.claim_id is not None and data.claim_id != question.claim_id:
        question.claim_id = data.claim_id
        changed_fields.append("claim_id")

    if data.assigned_to_id is not None and data.assigned_to_id != question.assigned_to_id:
        question.assigned_to_id = data.assigned_to_id
        changed_fields.append("assigned_to_id")

    if data.due_date is not None and data.due_date != question.due_date:
        question.due_date = data.due_date
        changed_fields.append("due_date")

    if data.priority is not None:
        try:
            enum_priority = Priority(data.priority.upper())
            if question.priority != enum_priority:
                question.priority = enum_priority
                changed_fields.append("priority")
        except ValueError:
            pass

    if data.status is not None:
        status_raw = data.status.upper().strip()
        if status_raw == "REOPENED":
            target_status = QuestionStatus.OPEN
        else:
            try:
                target_status = QuestionStatus(status_raw)
            except ValueError:
                raise ValueError(f"Invalid question status: '{data.status}'")

        if target_status != question.status:
            allowed = VALID_QUESTION_TRANSITIONS.get(question.status, set())
            if target_status not in allowed:
                raise ValueError(f"Invalid transition from {question.status.value} to {target_status.value}")
            old_status = question.status
            question.status = target_status
            changed_fields.append(f"status({old_status.value}->{target_status.value})")

    try:
        db.flush()

        if changed_fields:
            create_audit_event(
                db,
                actor_id=user_id,
                action="question.updated",
                entity_type="question",
                entity_id=question.id,
                details={"changes": changed_fields},
                summary=f"Updated question #{question.id}: {', '.join(changed_fields)}",
            )

        db.commit()
        db.refresh(question)
    except Exception:
        db.rollback()
        raise

    publish_case_event(
        case_id=question.case_id,
        event_type="question.answered",
        entity_id=str(question.id),
    )
    return _to_question_out(question)


def add_response(
    db: Session,
    *,
    question_id: uuid.UUID,
    user_id: uuid.UUID,
    response_text: str,
) -> QuestionOut:
    """Submit an answer to a question."""
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise ValueError("Question not found")
    if not response_text or not response_text.strip():
        raise ValueError("Response text cannot be empty")
    if question.status in (QuestionStatus.DISMISSED, QuestionStatus.CANCELLED):
        raise ValueError(f"Cannot answer a question in status '{question.status.value}'")
    if question.status == QuestionStatus.RESOLVED:
        raise ValueError("Cannot answer an already resolved question; reopen the question first")

    response = QuestionResponse(
        question_id=question.id,
        respondent_id=user_id,
        response_text=response_text.strip(),
        review_state=QuestionResponseReviewState.PENDING_REVIEW,
    )
    db.add(response)
    question.status = QuestionStatus.ANSWERED

    try:
        db.flush()

        create_audit_event(
            db,
            actor_id=user_id,
            action="question.answered",
            entity_type="question",
            entity_id=question.id,
            details={"question_id": str(question.id)},
            summary=f"Answered question #{question.id}",
        )
        db.commit()
        db.refresh(question)
    except Exception:
        db.rollback()
        raise

    publish_case_event(
        case_id=question.case_id,
        event_type="question.answered",
        entity_id=str(question.id),
    )
    return _to_question_out(question)
    publish_case_event(
        case_id=question.case_id,
        event_type="question.answered",
        entity_id=str(question.id),
    )
    return _to_question_out(question)


def _resolve_primary_transfer_pack(db: Session, *, question: Question) -> TransferPack | None:
    """Resolve the authoritative primary Transfer Pack for standalone Q&A promotion."""
    case_packs = (
        db.query(TransferPack)
        .filter(TransferPack.case_id == question.case_id)
        .order_by(TransferPack.sort_order.asc(), TransferPack.created_at.asc())
        .all()
    )
    if not case_packs:
        return None

    # 1. If question targets an existing pack in this same case, promote there
    if question.transfer_pack_id:
        targeted = next((p for p in case_packs if p.id == question.transfer_pack_id), None)
        if targeted:
            return targeted

    # 2. Explicit primary designation on the case
    explicit_primary = next((p for p in case_packs if getattr(p, "is_primary", False)), None)
    if explicit_primary:
        return explicit_primary

    # 3. Deterministic domain pack (prefer non-cross-cutting pack first)
    domain_packs = [
        p
        for p in case_packs
        if (p.component_area or "").lower() != "cross-cutting"
        and "cross-cutting" not in (p.name or "").lower()
    ]
    return domain_packs[0] if domain_packs else case_packs[0]


def _extract_valid_source_record_ids(
    db: Session,
    *,
    case_id: uuid.UUID,
    evidence_refs: list[dict[str, Any]] | None,
) -> list[uuid.UUID]:
    """Filter cited evidence_json to verified case-scoped non-deleted SourceRecord UUIDs."""
    if not evidence_refs:
        return []
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        return []

    case_sources = db.query(CaseSource).filter(CaseSource.case_id == case_id).all()
    allowed_src_ids = (
        {cs.connected_source_id for cs in case_sources}
        if case_sources
        else {s.id for s in db.query(ConnectedSource).filter(ConnectedSource.project_id == case.project_id).all()}
    )

    candidate_uuids: list[uuid.UUID] = []
    for ref in evidence_refs:
        if not isinstance(ref, dict):
            continue
        if str(ref.get("source_type") or "").upper() != "SOURCE_RECORD":
            continue
        try:
            candidate_uuids.append(uuid.UUID(str(ref.get("source_id"))))
        except (TypeError, ValueError):
            continue

    if not candidate_uuids or not allowed_src_ids:
        return []

    rows = (
        db.query(SourceRecord.id)
        .filter(
            SourceRecord.id.in_(candidate_uuids),
            SourceRecord.connected_source_id.in_(allowed_src_ids),
        )
        .all()
    )
    return [r[0] for r in rows]


def _promote_or_apply_clarification(
    db: Session,
    *,
    question: Question,
    target_response: QuestionResponse,
    reviewer: User,
    act: str,
    now_iso: str,
) -> dict[str, Any]:
    """Atomically apply accepted clarification to linked claim OR promote standalone Q&A once."""
    answer_text = (target_response.response_text or "").strip()
    valid_sr_ids = _extract_valid_source_record_ids(
        db,
        case_id=question.case_id,
        evidence_refs=getattr(target_response, "evidence_json", None),
    )
    is_ai = bool(getattr(target_response, "is_ai_generated", False))
    human_confirmed = (not is_ai) or (act == "amend")

    # Case A: Question linked to an existing claim -> traceable clarification revision
    if question.claim_id is not None:
        claim = db.query(Claim).filter(Claim.id == question.claim_id).first()
        if not claim:
            raise ValueError("Linked claim no longer exists")
        pack = db.query(TransferPack).filter(TransferPack.id == claim.transfer_pack_id).first()
        if not pack or pack.case_id != question.case_id:
            raise ValueError("Cross-case claim clarification rejected")

        marker = f"[Clarification Q#{str(question.id)[:8]} / R#{str(target_response.id)[:8]}]"
        if not claim.original_body_text:
            claim.original_body_text = claim.body_text

        prov = dict(getattr(claim, "provenance_json", None) or {})
        revisions = list(prov.get("revisions") or [])

        if marker not in (claim.body_text or ""):
            prov_label = "AI draft verified & amended by reviewer" if (is_ai and act == "amend") else (
                "AI draft accepted by reviewer" if is_ai else "Human-confirmed answer accepted by reviewer"
            )
            clarification_block = (
                f"\n\n---\n{marker} ({now_iso[:10]}) — {prov_label} ({reviewer.display_name}):\n"
                f"{answer_text}"
            )
            claim.body_text = ((claim.body_text or "").rstrip() + clarification_block).strip()
            revisions.append({
                "question_id": str(question.id),
                "response_id": str(target_response.id),
                "applied_at": now_iso,
                "reviewer_id": str(reviewer.id),
                "reviewer_name": reviewer.display_name,
                "is_ai_drafted": is_ai,
                "human_confirmed": True,
                "answer_text": answer_text,
                "cited_source_record_ids": [str(u) for u in valid_sr_ids],
            })
            prov["revisions"] = revisions
            prov["human_confirmed"] = True
            claim.provenance_json = prov

            # Link newly verified source citations if not already present
            existing_sr_links = {
                ev.source_record_id
                for ev in db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim.id).all()
                if ev.source_record_id
            }
            for sr_uuid in valid_sr_ids:
                if sr_uuid not in existing_sr_links:
                    db.add(
                        ClaimEvidence(
                            claim_id=claim.id,
                            source_record_id=sr_uuid,
                            excerpt=answer_text[:180],
                            locator=f"Cited in Q&A #{str(question.id)[:8]}",
                            evidence_type=EvidenceType.DIRECT_REFERENCE,
                            is_restricted=False,
                        )
                    )

            # Honestly re-evaluate evidence_state: human confirmation alone != repository SUPPORTED
            if claim.evidence_state == EvidenceState.UNKNOWN:
                claim.evidence_state = EvidenceState.SUPPORTED if valid_sr_ids else EvidenceState.INFERRED
            elif valid_sr_ids and claim.evidence_state == EvidenceState.INFERRED:
                claim.evidence_state = EvidenceState.SUPPORTED

            # Clear NEEDS_CLARIFICATION -> back to PENDING_REVIEW so reviewer verifies full revised claim
            if claim.review_state == ReviewState.NEEDS_CLARIFICATION:
                claim.review_state = ReviewState.PENDING_REVIEW
            claim.review_notes = f"Clarification accepted from question '{question.question_text[:60]}'"

            create_audit_event(
                db,
                actor_id=reviewer.id,
                action="claim.clarified_from_question",
                entity_type="claim",
                entity_id=claim.id,
                details={
                    "question_id": str(question.id),
                    "response_id": str(target_response.id),
                    "has_repo_citations": bool(valid_sr_ids),
                    "evidence_state": claim.evidence_state.value,
                    "review_state": claim.review_state.value,
                },
                summary=f"Applied accepted clarification to linked claim '{claim.title[:60]}'",
            )

        return {
            "status": "linked_claim_updated",
            "claim_id": str(claim.id),
            "pack_id": str(pack.id),
            "pack_name": pack.name,
            "message": f"Clarification applied to linked claim in '{pack.name}'.",
        }

    # Case B: Standalone Question -> idempotently promote to ONE Operational Note
    if len(answer_text) < 5:
        return {
            "status": "skipped_empty",
            "message": "Accepted response was empty; no Operational Note created.",
        }

    if is_ai and act != "amend" and getattr(target_response, "answer_status", None) == "insufficient":
        return {
            "status": "skipped_non_informative",
            "message": "Insufficient-evidence AI draft acknowledged; no Operational Note created.",
        }

    existing_promoted = db.query(Claim).filter(Claim.origin_question_id == question.id).first()
    if existing_promoted:
        existing_pack = db.query(TransferPack).filter(TransferPack.id == existing_promoted.transfer_pack_id).first()
        return {
            "status": "already_promoted",
            "claim_id": str(existing_promoted.id),
            "pack_id": str(existing_promoted.transfer_pack_id),
            "pack_name": existing_pack.name if existing_pack else "Transfer Pack",
            "message": "Operational Note already exists for this question.",
        }

    primary_pack = _resolve_primary_transfer_pack(db, question=question)
    if not primary_pack:
        return {
            "status": "skipped_no_primary_pack",
            "message": "No primary Transfer Pack exists in this handover case; question resolved without claim creation.",
        }

    if primary_pack.case_id != question.case_id:
        raise ValueError("Resolved pack does not belong to this case")

    # Never invent repository evidence when only human confirmation exists
    ev_state = EvidenceState.SUPPORTED if valid_sr_ids else EvidenceState.INFERRED
    new_claim = Claim(
        id=uuid.uuid4(),
        transfer_pack_id=primary_pack.id,
        claim_type=ClaimType.OPERATIONAL_NOTE,
        title=f"Clarification: {question.question_text[:140].strip()}",
        body_text=answer_text,
        evidence_state=ev_state,
        freshness=Freshness.CURRENT,
        review_state=ReviewState.ACCEPTED,
        priority=question.priority or Priority.MEDIUM,
        reviewed_by=reviewer.id,
        reviewed_at=now_iso,
        review_notes=f"Promoted from accepted Q&A ({'Human-confirmed' if human_confirmed else 'AI draft verified by reviewer'}).",
        origin_question_id=question.id,
        provenance_json={
            "source": "accepted_qa",
            "origin_question_id": str(question.id),
            "origin_response_id": str(target_response.id),
            "is_ai_drafted": is_ai,
            "human_confirmed": True,
            "reviewer_id": str(reviewer.id),
            "reviewer_name": reviewer.display_name,
            "reviewed_at": now_iso,
            "cited_source_record_ids": [str(u) for u in valid_sr_ids],
        },
    )
    db.add(new_claim)
    db.flush()

    if valid_sr_ids:
        for sr_uuid in valid_sr_ids:
            db.add(
                ClaimEvidence(
                    claim_id=new_claim.id,
                    source_record_id=sr_uuid,
                    excerpt=answer_text[:200],
                    locator=f"Q&A Citation #{str(question.id)[:8]}",
                    evidence_type=EvidenceType.DIRECT_REFERENCE,
                    is_restricted=False,
                )
            )
    else:
        db.add(
            ClaimEvidence(
                claim_id=new_claim.id,
                source_record_id=None,
                excerpt=answer_text[:200],
                locator=f"Human-Confirmed Q&A #{str(question.id)[:8]}",
                evidence_type=EvidenceType.CONTEXTUAL,
                is_restricted=False,
            )
        )

    question.claim_id = new_claim.id
    db.flush()

    create_audit_event(
        db,
        actor_id=reviewer.id,
        action="claim.promoted_from_question",
        entity_type="claim",
        entity_id=new_claim.id,
        details={
            "question_id": str(question.id),
            "response_id": str(target_response.id),
            "transfer_pack_id": str(primary_pack.id),
            "evidence_state": ev_state.value,
            "has_repo_citations": bool(valid_sr_ids),
        },
        summary=f"Promoted accepted Q&A to Operational Note in '{primary_pack.name}'",
    )

    return {
        "status": "promoted_operational_note",
        "claim_id": str(new_claim.id),
        "pack_id": str(primary_pack.id),
        "pack_name": primary_pack.name,
        "message": f"Operational Note added to Transfer Pack '{primary_pack.name}'.",
    }


def review_response(
    db: Session,
    *,
    question_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    notes: str | None = None,
    response_id: uuid.UUID | None = None,
    amended_text: str | None = None,
) -> QuestionOut:
    """Accept, reject, or amend a response to a question (atomically promoting/updating knowledge)."""
    q_query = db.query(Question).filter(Question.id == question_id)
    try:
        if db.bind and db.bind.dialect.name != "sqlite":
            q_query = q_query.with_for_update()
    except Exception:
        pass
    question = (
        q_query
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.claim),
            joinedload(Question.assigned_to),
            joinedload(Question.created_by),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .first()
    )
    if not question:
        raise ValueError("Question not found")

    reviewer = db.query(User).filter(User.id == user_id).first()
    if not reviewer:
        raise ForbiddenError("Reviewer not found")

    caps, _, _ = get_user_context_capabilities(db, reviewer, case_id=question.case_id)
    if "question.review" not in caps:
        raise ForbiddenError("You do not have permission to review answers on this handover case.")

    if not question.responses:
        raise ValueError("No responses found for this question")

    if response_id is not None:
        target_response = next((r for r in question.responses if r.id == response_id), None)
        if not target_response:
            raise ValueError("Question response not found on this question")
    else:
        target_response = question.responses[-1]

    now_iso = datetime.now(timezone.utc).isoformat()
    act = action.lower().strip()
    promotion_result: dict[str, Any] | None = None

    if act == "accept":
        target_response.review_state = QuestionResponseReviewState.ACCEPTED
        target_response.reviewed_by_id = user_id
        target_response.reviewed_at = now_iso
        target_response.review_notes = notes
        question.status = QuestionStatus.RESOLVED
        promotion_result = _promote_or_apply_clarification(
            db,
            question=question,
            target_response=target_response,
            reviewer=reviewer,
            act=act,
            now_iso=now_iso,
        )
    elif act == "reject":
        target_response.review_state = QuestionResponseReviewState.REJECTED
        target_response.reviewed_by_id = user_id
        target_response.reviewed_at = now_iso
        target_response.review_notes = notes
        question.status = QuestionStatus.OPEN  # Re-opens question for re-answering
    elif act == "amend":
        if amended_text is not None:
            cleaned = amended_text.strip()
            if not cleaned:
                raise ValueError("Amended answer text cannot be empty")
            prov = dict(getattr(target_response, "provenance_json", None) or {})
            prov.setdefault("original_text_before_amendment", target_response.response_text)
            prov["amended_by_id"] = str(user_id)
            prov["amended_at"] = now_iso
            target_response.provenance_json = prov
            target_response.response_text = cleaned
        target_response.review_state = QuestionResponseReviewState.AMENDED
        target_response.reviewed_by_id = user_id
        target_response.reviewed_at = now_iso
        target_response.review_notes = notes
        question.status = QuestionStatus.RESOLVED
        promotion_result = _promote_or_apply_clarification(
            db,
            question=question,
            target_response=target_response,
            reviewer=reviewer,
            act=act,
            now_iso=now_iso,
        )
    else:
        raise ValueError(f"Unsupported question review action: '{action}'. Expected accept, reject, or amend.")

    try:
        db.flush()

        create_audit_event(
            db,
            actor_id=user_id,
            action=f"question.response_{act}",
            entity_type="question",
            entity_id=question.id,
            details={
                "action": act,
                "notes": notes,
                "response_id": str(target_response.id),
                "promotion_result": promotion_result,
            },
            summary=f"{act.capitalize()}ed answer for question #{question.id}",
        )
        db.commit()
        db.refresh(question)
    except Exception:
        db.rollback()
        raise

    publish_case_event(
        case_id=question.case_id,
        event_type="question.reviewed",
        entity_id=str(question.id),
    )
    return _to_question_out(question, promotion_result=promotion_result)


def generate_ai_answer(
    db: Session,
    *,
    question_id: uuid.UUID,
    user_id: uuid.UUID,
) -> QuestionOut:
    """Generate a strictly grounded AI draft answer (ALWAYS PENDING_REVIEW, never auto-accepted)."""
    question = (
        db.query(Question)
        .options(
            joinedload(Question.case),
            joinedload(Question.transfer_pack),
            joinedload(Question.claim),
            joinedload(Question.responses).joinedload(QuestionResponse.respondent),
            joinedload(Question.responses).joinedload(QuestionResponse.reviewer),
        )
        .filter(Question.id == question_id)
        .first()
    )
    if not question:
        raise ValueError("Question not found")

    if question.status in (QuestionStatus.DISMISSED, QuestionStatus.CANCELLED):
        raise ValueError(f"Cannot generate AI draft for question in status '{question.status.value}'")

    requester = db.query(User).filter(User.id == user_id).first()
    if not requester:
        raise ForbiddenError("Requester not found")

    caps, ws_roles, proj_roles = get_user_context_capabilities(db, requester, case_id=question.case_id)
    if "question.generate_ai" not in caps:
        raise ForbiddenError("You do not have permission to generate AI drafts for this case.")

    case = question.case or db.query(HandoverCase).filter(HandoverCase.id == question.case_id).first()
    if not case:
        raise ValueError("Parent Handover Case not found")

    # Concurrency guard preventing duplicate parallel draft generation for same question
    with _ACTIVE_AI_GEN_LOCK:
        if question.id in _ACTIVE_AI_QUESTIONS:
            raise ConflictError("AI draft generation is already running for this question.")
        _ACTIVE_AI_QUESTIONS.add(question.id)

    try:
        from app.modules.evidence.clearance import (
            get_restricted_claim_ids,
            has_restricted_clearance,
            resolve_case_source_ids,
        )

        allow_restricted = has_restricted_clearance(
            db,
            user_id=requester.id,
            project_id=case.project_id,
            case_id=case.id,
            user=requester,
        )
        source_ids = resolve_case_source_ids(
            db,
            case_id=case.id,
            project_id=case.project_id,
        )

        sr_query = (
            db.query(SourceRecord).filter(SourceRecord.connected_source_id.in_(source_ids))
            if source_ids
            else None
        )
        candidate_records: list[SourceRecord] = []
        if sr_query is not None:
            if not allow_restricted:
                sr_query = sr_query.filter(SourceRecord.sensitivity != Sensitivity.RESTRICTED)
            candidate_records = sr_query.order_by(SourceRecord.created_at.desc()).limit(300).all()

        pack_ids = [
            p.id
            for p in db.query(TransferPack).filter(TransferPack.case_id == case.id).all()
        ]
        candidate_claims: list[Claim] = []
        if pack_ids:
            all_claims = (
                db.query(Claim)
                .filter(
                    Claim.transfer_pack_id.in_(pack_ids),
                    Claim.review_state != ReviewState.REJECTED,
                )
                .all()
            )
            restricted_claim_ids = (
                get_restricted_claim_ids(db, claim_ids=[c.id for c in all_claims])
                if all_claims and not allow_restricted
                else set()
            )
            candidate_claims = [c for c in all_claims if c.id not in restricted_claim_ids]

        evidence_blocks, permitted_record_ids, permitted_claim_ids = select_qa_evidence_context(
            question_text=question.question_text,
            why_it_matters=question.why_it_matters,
            linked_claim_id=str(question.claim_id) if question.claim_id else None,
            source_records=candidate_records,
            claims=candidate_claims,
        )
        blocks_by_id = {b["id"]: b for b in evidence_blocks}

        user_prompt = build_qa_user_prompt(
            question_text=question.question_text,
            why_it_matters=question.why_it_matters,
            evidence_blocks=evidence_blocks,
        )

        provider = get_llm_provider()
        try:
            raw_qa_res, usage_meta = provider.answer_question(
                QA_SYSTEM_PROMPT,
                user_prompt,
                QuestionAnswerResult,
            )
            qa_res = QuestionAnswerResult.model_validate(raw_qa_res)
        except Exception as exc:
            logger.warning("Live LLM answer drafting failed (%s: %s); falling back cleanly", type(exc).__name__, exc)
            try:
                from app.integrations.llm.mock_provider import MockLLMProvider
                mock = MockLLMProvider()
                raw_qa_res, usage_meta = mock.answer_question(
                    QA_SYSTEM_PROMPT,
                    user_prompt,
                    QuestionAnswerResult,
                )
                usage_meta["fallback_used"] = True
                usage_meta["fallback_reason"] = f"AI drafting provider error ({type(exc).__name__}): {str(exc)[:200]}"
                qa_res = QuestionAnswerResult.model_validate(raw_qa_res)
            except Exception as inner_exc:
                logger.error("Mock fallback also failed: %s", inner_exc)
                usage_meta = {
                    "provider_mode": "error_fallback",
                    "model_used": "none",
                    "fallback_used": True,
                    "fallback_reason": f"AI drafting failed ({type(exc).__name__}): {str(exc)[:200]}",
                }
                qa_res = QuestionAnswerResult(
                    answer_text="AI draft could not be generated due to a temporary service timeout or format error.",
                    answer_status="insufficient",
                    limitations=f"AI generation encountered a temporary error ({type(exc).__name__}). Please provide a manual answer or retry.",
                    evidence_references=[],
                    conflicts=[],
                    confidence_diagnostic="error",
                )

        validated_refs: list[dict[str, Any]] = []
        rejected_ref_ids: list[str] = []
        seen_ref_keys: set[tuple[str, str]] = set()

        for ref in qa_res.evidence_references:
            sid = str(ref.source_id or "").strip()
            stype = str(ref.source_type or "SOURCE_RECORD").upper()
            in_permitted = (
                (stype == "CLAIM" and sid in permitted_claim_ids)
                or (stype == "SOURCE_RECORD" and sid in permitted_record_ids)
                or (sid in blocks_by_id)
            )
            if not in_permitted:
                rejected_ref_ids.append(sid)
                continue

            block = blocks_by_id[sid]
            actual_stype = block["source_class"]
            dedup_key = (actual_stype, sid)
            if dedup_key in seen_ref_keys:
                continue
            seen_ref_keys.add(dedup_key)

            validated_refs.append({
                "source_id": sid,
                "source_type": actual_stype,
                "title": ref.title or block["title"],
                "excerpt": ref.excerpt or block["body"][:160],
                "locator": ref.locator or block["locator"],
                "relevance": ref.relevance or "Grounded case evidence",
                "is_stale": bool(block.get("is_stale") or ref.is_stale),
            })

        answer_status = qa_res.answer_status
        answer_text = (qa_res.answer_text or "").strip()
        limitations = qa_res.limitations

        if answer_status != "insufficient" and not validated_refs:
            answer_status = "insufficient"
            extra_limit = (
                "No verifiable citations within your permitted case sources remained after validation."
            )
            limitations = f"{limitations} {extra_limit}".strip() if limitations else extra_limit
            if not answer_text or rejected_ref_ids:
                answer_text = (
                    "The answer to this question is not established by the verified, permitted sources "
                    "available in this handover case."
                )

        if any(r.get("is_stale") for r in validated_refs):
            stale_note = "Potentially stale evidence cited; verify against latest source state."
            if not limitations or "stale" not in limitations.lower():
                limitations = f"{limitations} {stale_note}".strip() if limitations else stale_note

        model_used = usage_meta.get("model_used") or provider.get_model_name()
        provider_mode = usage_meta.get("provider_mode") or ("mock" if "mock" in model_used.lower() else "live")
        fallback_used = bool(usage_meta.get("fallback_used", False))
        fallback_reason = usage_meta.get("fallback_reason")
        generated_at_iso = datetime.now(timezone.utc).isoformat()

        provenance = {
            "prompt_version": QA_PROMPT_VERSION,
            "provider_mode": provider_mode,
            "model_used": model_used,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "requested_by_id": str(user_id),
            "generated_at": generated_at_iso,
            "retrieved_context_count": len(evidence_blocks),
            "rejected_citation_ids": rejected_ref_ids,
            "confidence_diagnostic": qa_res.confidence_diagnostic,
        }

        ai_response = QuestionResponse(
            question_id=question.id,
            respondent_id=None,
            response_text=answer_text,
            review_state=QuestionResponseReviewState.PENDING_REVIEW,
            is_ai_generated=True,
            ai_provider=provider_mode,
            ai_model=model_used,
            answer_status=answer_status,
            evidence_json=validated_refs,
            limitations=limitations,
            conflicts_json=list(qa_res.conflicts or []),
            provenance_json=provenance,
        )
        db.add(ai_response)
        question.status = QuestionStatus.ANSWERED
        db.flush()

        create_audit_event(
            db,
            actor_id=user_id,
            action="question.ai_answer_generated",
            entity_type="question",
            entity_id=question.id,
            details={
                "question_id": str(question.id),
                "response_id": str(ai_response.id),
                "provider_mode": provider_mode,
                "model_used": model_used,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "answer_status": answer_status,
                "cited_count": len(validated_refs),
                "rejected_citations_count": len(rejected_ref_ids),
            },
            summary=(
                f"Generated AI draft answer ({provider_mode}/{model_used}, status={answer_status}) "
                f"for question #{question.id} with {len(validated_refs)} citation(s)"
            ),
        )

        try:
            db.commit()
            db.refresh(question)
        except Exception:
            db.rollback()
            raise
        return _to_question_out(question)
    finally:
        with _ACTIVE_AI_GEN_LOCK:
            _ACTIVE_AI_QUESTIONS.discard(question.id)
