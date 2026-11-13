"""Clearance-first hybrid semantic + lexical retrieval over indexed KnowledgeChunks."""

from __future__ import annotations

import math
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.enums import Sensitivity
from app.integrations.llm.embeddings import embed_query_safe
from app.modules.rag.models import KnowledgeChunk

_TOKEN_RE = re.compile(r"[a-z0-9_./#-]{2,}")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def retrieve_permitted_chunks(
    db: Session,
    *,
    case_id: uuid.UUID,
    context_mode: str,
    pinned_version_id: uuid.UUID | None,
    allow_restricted: bool,
    query_text: str,
    top_k: int = 8,
) -> tuple[list[KnowledgeChunk], bool, str]:
    """Retrieve relevant chunks enforcing SQL sensitivity filters BEFORE vector/lexical scoring.

    Returns ``(top_chunks, restricted_evidence_excluded, retrieval_mode)``.
    """
    base_filter = [
        KnowledgeChunk.case_id == case_id,
        KnowledgeChunk.context_mode == context_mode,
    ]
    if pinned_version_id is not None:
        base_filter.append(KnowledgeChunk.version_id == pinned_version_id)
    else:
        base_filter.append(KnowledgeChunk.version_id.is_(None))

    # Generic check only: does restricted content exist in this scope (without loading restricted rows)?
    restricted_excluded = False
    if not allow_restricted:
        has_restricted = (
            db.query(KnowledgeChunk.id)
            .filter(*base_filter, KnowledgeChunk.sensitivity == Sensitivity.RESTRICTED)
            .first()
            is not None
        )
        restricted_excluded = has_restricted
        base_filter.append(KnowledgeChunk.sensitivity != Sensitivity.RESTRICTED)

    # Only permitted rows ever leave SQL into Python memory
    candidates: list[KnowledgeChunk] = (
        db.query(KnowledgeChunk)
        .filter(*base_filter)
        .order_by(KnowledgeChunk.indexed_at.asc(), KnowledgeChunk.id.asc())
        .all()
    )
    if not candidates:
        return [], restricted_excluded, "lexical_only"

    q_tokens = _tokenize(query_text)
    if not q_tokens:
        return candidates[:top_k], restricted_excluded, "lexical_only"

    # Attempt query embedding only AFTER RBAC + SQL clearance filtering
    q_embed = embed_query_safe(query_text)
    has_live_q_vec = bool(q_embed.vectors and q_embed.vectors[0])
    q_vec = q_embed.vectors[0] if has_live_q_vec else None

    any_matching_chunk_vec = False
    scored: list[tuple[float, KnowledgeChunk]] = []

    for ch in candidates:
        title_tokens = _tokenize(ch.title)
        body_tokens = _tokenize(ch.content_text)
        loc_str = str((ch.locator_json or {}).get("locator") or "")
        loc_tokens = _tokenize(loc_str)

        all_tokens = title_tokens | body_tokens | loc_tokens
        overlap_count = len(q_tokens & all_tokens)
        lexical_score = overlap_count / max(1, min(len(q_tokens), 8))

        # Exact identifier boost (PR numbers, commit SHAs, file paths, title phrases)
        id_boost = 0.0
        q_low = query_text.lower()
        if loc_str and len(loc_str) > 3 and loc_str.lower() in q_low:
            id_boost += 0.35
        if len(q_tokens & title_tokens) >= 2:
            id_boost += 0.20

        vec_score = 0.0
        used_semantic = False
        if (
            q_vec is not None
            and isinstance(ch.embedding_json, list)
            and ch.embedding_model == q_embed.model_id
            and ch.embedding_dimension == len(q_vec)
        ):
            vec_score = _cosine_similarity(q_vec, ch.embedding_json)
            used_semantic = True
            any_matching_chunk_vec = True

        if used_semantic:
            combined = 0.65 * vec_score + 0.35 * min(1.0, lexical_score + id_boost)
        else:
            combined = min(1.0, lexical_score + id_boost)

        if combined > 0.05:
            scored.append((combined, ch))

    retrieval_mode = "hybrid_semantic" if any_matching_chunk_vec else "lexical_only"
    scored.sort(key=lambda tup: (-tup[0], str(tup[1].id)))

    # Deduplicate near-identical content hashes while preserving top ranking
    selected: list[KnowledgeChunk] = []
    seen_hashes: set[str] = set()
    for _, ch in scored:
        if ch.content_hash in seen_hashes:
            continue
        seen_hashes.add(ch.content_hash)
        selected.append(ch)
        if len(selected) >= top_k:
            break

    return selected, restricted_excluded, retrieval_mode
