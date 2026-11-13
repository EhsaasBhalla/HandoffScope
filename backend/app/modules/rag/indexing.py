"""Semantic/boundary-aware chunking and idempotent RAG indexing pipeline."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.enums import (
    ProcessingStatus,
    QuestionResponseReviewState,
    Sensitivity,
)
from app.integrations.llm.embeddings import embed_documents_safe
from app.modules.documents.models import Document
from app.modules.evidence.clearance import resolve_case_source_ids
from app.modules.evidence.models import ClaimEvidence
from app.modules.handover_cases.models import HandoverCase
from app.modules.ingestion.models import SourceRecord
from app.modules.projects.models import Project
from app.modules.questions.models import Question, QuestionResponse
from app.modules.rag.models import KnowledgeChunk
from app.modules.reviews.models import HandoverVersion
from app.modules.transfer_packs.models import Claim, TransferPack

CONTEXT_APPROVED = "APPROVED_SNAPSHOT"
CONTEXT_DRAFT = "DRAFT_CONTEXT"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_preserving_boundaries(
    text: str,
    *,
    max_chars: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Split long documents on Markdown headings/paragraphs with configurable overlap."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    limit = max_chars or settings.RAG_CHUNK_CHAR_LIMIT
    ov = overlap if overlap is not None else settings.RAG_CHUNK_OVERLAP
    if len(cleaned) <= limit:
        return [cleaned]

    blocks = re.split(r"\n(?=#{1,4}\s)|\n\s*\n", cleaned)
    chunks: list[str] = []
    current = ""
    for blk in blocks:
        blk = blk.strip()
        if not blk:
            continue
        if len(current) + len(blk) + 2 <= limit:
            current = f"{current}\n\n{blk}".strip() if current else blk
        else:
            if current:
                chunks.append(current)
            if len(blk) <= limit:
                tail = current[-ov:] if current and ov > 0 else ""
                current = f"{tail}\n{blk}".strip() if tail and len(tail) + len(blk) + 1 <= limit else blk
            else:
                start = 0
                step = max(200, limit - ov)
                while start < len(blk):
                    chunks.append(blk[start : start + limit].strip())
                    start += step
                current = ""
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def _upsert_chunks(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    version_id: uuid.UUID | None,
    context_mode: str,
    draft_items: list[dict[str, Any]],
) -> tuple[int, str, str, int]:
    """Deduplicate and embed chunks idempotently; remove stale draft chunks if content changed."""
    if not draft_items:
        return 0, "lexical_only", "lexical", 0

    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in draft_items:
        c_hash = _sha256_text(item["content_text"])
        key = (item["source_kind"], str(item["source_ref_id"]), c_hash)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        item["content_hash"] = c_hash
        deduped.append(item)

    existing_rows = (
        db.query(KnowledgeChunk)
        .filter(
            KnowledgeChunk.case_id == case_id,
            KnowledgeChunk.context_mode == context_mode,
            KnowledgeChunk.version_id == version_id
            if version_id is not None
            else KnowledgeChunk.version_id.is_(None),
        )
        .all()
    )
    existing_by_key = {
        (r.source_kind, r.source_ref_id, r.content_hash): r for r in existing_rows
    }

    target_keys = {(d["source_kind"], str(d["source_ref_id"]), d["content_hash"]) for d in deduped}
    if context_mode == CONTEXT_DRAFT:
        for row in existing_rows:
            rkey = (row.source_kind, row.source_ref_id, row.content_hash)
            if rkey not in target_keys:
                db.delete(row)

    to_create: list[dict[str, Any]] = []
    for d in deduped:
        rkey = (d["source_kind"], str(d["source_ref_id"]), d["content_hash"])
        if rkey not in existing_by_key:
            to_create.append(d)

    embed_res = embed_documents_safe([f"{d['title']}\n\n{d['content_text']}" for d in to_create]) if to_create else None
    created_count = 0
    now = datetime.now(timezone.utc)

    for idx, d in enumerate(to_create):
        vec = (
            embed_res.vectors[idx]
            if embed_res and embed_res.vectors and idx < len(embed_res.vectors)
            else None
        )
        row = KnowledgeChunk(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            case_id=case_id,
            version_id=version_id,
            context_mode=context_mode,
            source_kind=d["source_kind"],
            source_ref_id=str(d["source_ref_id"]),
            source_revision=d.get("source_revision"),
            sensitivity=d["sensitivity"],
            title=d["title"][:500],
            content_text=d["content_text"],
            content_hash=d["content_hash"],
            locator_json=d.get("locator_json"),
            metadata_json=d.get("metadata_json"),
            embedding_json=vec,
            embedding_model=embed_res.model_id if embed_res else "lexical",
            embedding_dimension=embed_res.dimension if embed_res else 0,
            indexed_at=now,
        )
        db.add(row)
        created_count += 1

    db.flush()
    mode_used = embed_res.provider_mode if embed_res else "lexical_only"
    model_used = embed_res.model_id if embed_res else "lexical"
    dim_used = embed_res.dimension if embed_res else 0
    return len(deduped), mode_used, model_used, dim_used


def index_approved_version_chunks(
    db: Session,
    *,
    case_id: uuid.UUID,
    version_id: uuid.UUID,
) -> tuple[int, str, str, int]:
    """Index knowledge chunks strictly from frozen HandoverVersion.snapshot_json."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError("Handover case not found")
    proj = db.query(Project).filter(Project.id == case.project_id).first()
    if not proj:
        raise ValueError("Project not found")
    version = (
        db.query(HandoverVersion)
        .filter(HandoverVersion.id == version_id, HandoverVersion.case_id == case_id)
        .first()
    )
    if not version:
        raise ValueError("Approved handover version not found for this case")

    snap = version.snapshot_json or {}
    packs = snap.get("transfer_packs") or snap.get("packs") or []
    draft_items: list[dict[str, Any]] = []

    for pack in packs:
        if not isinstance(pack, dict):
            continue
        pack_name = str(pack.get("name") or "Transfer Pack")
        for c in pack.get("claims", []):
            if not isinstance(c, dict):
                continue
            ev_list = c.get("evidence") or []
            has_restricted = any(bool(ev.get("is_restricted")) for ev in ev_list if isinstance(ev, dict))
            sens = Sensitivity.RESTRICTED if has_restricted else Sensitivity.GENERAL

            ev_snippets = []
            first_locator = None
            for ev in ev_list:
                if not isinstance(ev, dict):
                    continue
                if not first_locator and ev.get("locator"):
                    first_locator = ev.get("locator")
                if ev.get("excerpt"):
                    ev_snippets.append(f"[{ev.get('locator') or 'Citation'}] {ev.get('excerpt')}")

            body = "\n".join(
                part
                for part in [
                    f"Claim ({c.get('claim_type', 'CLAIM')} | {c.get('evidence_state', 'UNKNOWN')} | Review: {c.get('review_state', 'ACCEPTED')}):",
                    str(c.get("body_text") or ""),
                    ("Evidence Excerpts:\n" + "\n".join(ev_snippets)) if ev_snippets else "",
                ]
                if part
            )
            claim_ref_id = str(c.get("id") or uuid.uuid4())
            for seg_idx, chunk_text in enumerate(split_preserving_boundaries(body)):
                draft_items.append({
                    "source_kind": "CLAIM",
                    "source_ref_id": f"{claim_ref_id}#{seg_idx}" if seg_idx > 0 else claim_ref_id,
                    "source_revision": f"v{version.version_number}",
                    "sensitivity": sens,
                    "title": str(c.get("title") or "Claim"),
                    "content_text": chunk_text,
                    "locator_json": {"locator": first_locator or f"v{version.version_number}:{pack_name}", "pack_name": pack_name},
                    "metadata_json": {
                        "pack_name": pack_name,
                        "claim_type": c.get("claim_type"),
                        "evidence_state": c.get("evidence_state"),
                        "version_number": version.version_number,
                    },
                })

    # Also capture frozen Lead-override attestation if recorded
    override_meta = snap.get("override_metadata")
    if isinstance(override_meta, dict) and override_meta.get("override_reason"):
        draft_items.append({
            "source_kind": "CLAIM",
            "source_ref_id": f"override-v{version.version_number}",
            "source_revision": f"v{version.version_number}",
            "sensitivity": Sensitivity.GENERAL,
            "title": f"Lead Approval Override Attestation (v{version.version_number})",
            "content_text": (
                f"Overridden by {override_meta.get('overridden_by_name', 'Lead')}: "
                f"{override_meta.get('override_reason')}"
            ),
            "locator_json": {"locator": f"Version v{version.version_number} Override"},
            "metadata_json": {"version_number": version.version_number},
        })

    return _upsert_chunks(
        db,
        workspace_id=proj.workspace_id,
        project_id=proj.id,
        case_id=case.id,
        version_id=version.id,
        context_mode=CONTEXT_APPROVED,
        draft_items=draft_items,
    )


def index_draft_case_chunks(
    db: Session,
    *,
    case_id: uuid.UUID,
) -> tuple[int, str, str, int]:
    """Index live draft claims, permitted source records, documents, and accepted Q&A."""
    case = db.query(HandoverCase).filter(HandoverCase.id == case_id).first()
    if not case:
        raise ValueError("Handover case not found")
    proj = db.query(Project).filter(Project.id == case.project_id).first()
    if not proj:
        raise ValueError("Project not found")

    draft_items: list[dict[str, Any]] = []

    packs = db.query(TransferPack).filter(TransferPack.case_id == case.id).all()
    pack_map = {p.id: p.name for p in packs}
    if packs:
        claims = db.query(Claim).filter(Claim.transfer_pack_id.in_(list(pack_map.keys()))).all()
        for c in claims:
            evs = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == c.id).all()
            is_restr = any(ev.is_restricted for ev in evs)
            first_loc = next((ev.locator for ev in evs if ev.locator), None)
            draft_items.append({
                "source_kind": "CLAIM",
                "source_ref_id": str(c.id),
                "source_revision": c.updated_at.isoformat() if c.updated_at else "draft",
                "sensitivity": Sensitivity.RESTRICTED if is_restr else Sensitivity.GENERAL,
                "title": c.title,
                "content_text": c.body_text or c.title,
                "locator_json": {"locator": first_loc or pack_map.get(c.transfer_pack_id, "Transfer Pack")},
                "metadata_json": {
                    "pack_name": pack_map.get(c.transfer_pack_id),
                    "claim_type": c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type),
                    "evidence_state": c.evidence_state.value if hasattr(c.evidence_state, "value") else str(c.evidence_state),
                },
            })

    source_ids = resolve_case_source_ids(db, case_id=case.id, project_id=case.project_id)
    if source_ids:
        records = (
            db.query(SourceRecord)
            .filter(SourceRecord.connected_source_id.in_(source_ids))
            .order_by(SourceRecord.created_at.desc())
            .limit(200)
            .all()
        )
        for rec in records:
            text_body = f"{rec.title or ''}\n\n{rec.body or ''}".strip()
            for idx, seg in enumerate(split_preserving_boundaries(text_body)):
                draft_items.append({
                    "source_kind": "SOURCE_RECORD",
                    "source_ref_id": f"{rec.id}#{idx}" if idx > 0 else str(rec.id),
                    "source_revision": rec.external_updated_at.isoformat() if rec.external_updated_at else rec.external_id,
                    "sensitivity": rec.sensitivity or Sensitivity.GENERAL,
                    "title": rec.title or f"{rec.record_type.value} #{rec.external_id}",
                    "content_text": seg,
                    "locator_json": {"locator": f"{rec.record_type.value} #{rec.external_id}", "url": rec.url},
                    "metadata_json": {
                        "record_type": rec.record_type.value if hasattr(rec.record_type, "value") else str(rec.record_type),
                        "author": rec.author_name or rec.author_external_id,
                        "url": rec.url,
                    },
                })

    # Uploaded project documents already parsed
    docs = (
        db.query(Document)
        .filter(
            Document.project_id == case.project_id,
            Document.processing_status == ProcessingStatus.COMPLETED,
            Document.extracted_text.isnot(None),
        )
        .all()
    )
    for doc in docs:
        for idx, seg in enumerate(split_preserving_boundaries(doc.extracted_text or "")):
            draft_items.append({
                "source_kind": "DOCUMENT_SECTION",
                "source_ref_id": f"{doc.id}#sec-{idx + 1}",
                "source_revision": doc.file_hash,
                "sensitivity": doc.sensitivity or Sensitivity.GENERAL,
                "title": f"{doc.original_filename} (Section {idx + 1})",
                "content_text": seg,
                "locator_json": {"locator": f"{doc.original_filename}#section-{idx + 1}"},
                "metadata_json": {"document_id": str(doc.id)},
            })

    # Accepted Q&A answers
    questions = db.query(Question).filter(Question.case_id == case.id).all()
    for q in questions:
        accepted_resps = (
            db.query(QuestionResponse)
            .filter(
                QuestionResponse.question_id == q.id,
                QuestionResponse.review_state.in_([
                    QuestionResponseReviewState.ACCEPTED,
                    QuestionResponseReviewState.AMENDED,
                ]),
            )
            .all()
        )
        for resp in accepted_resps:
            draft_items.append({
                "source_kind": "QA_ANSWER",
                "source_ref_id": str(resp.id),
                "source_revision": resp.reviewed_at.isoformat() if resp.reviewed_at else "accepted",
                "sensitivity": Sensitivity.GENERAL,
                "title": f"Q&A: {q.question_text[:120]}",
                "content_text": f"Question: {q.question_text}\nAccepted Answer: {resp.response_text}",
                "locator_json": {"locator": f"Question #{str(q.id)[:8]}"},
                "metadata_json": {"question_id": str(q.id)},
            })

    return _upsert_chunks(
        db,
        workspace_id=proj.workspace_id,
        project_id=proj.id,
        case_id=case.id,
        version_id=None,
        context_mode=CONTEXT_DRAFT,
        draft_items=draft_items,
    )
