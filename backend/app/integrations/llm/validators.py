"""Evidence validation pipeline for LLM extraction results.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.enums import Sensitivity
from app.integrations.llm.schemas.extraction import EvidenceState, ExtractionResult


@dataclass
class ValidationError:
    message: str
    item_title: str | None = None
    source_record_id: str | None = None
    severity: str = "error"  # "error" | "warning"


def validate_extraction_result(
    result: ExtractionResult,
    input_source_ids: set[str],
    source_records_by_id: dict[str, Any],
) -> tuple[ExtractionResult, list[ValidationError]]:
    """Validate all evidence references in an extraction result."""
    errors: list[ValidationError] = []

    # Helper to validate a claim item
    def _validate_claim(item: Any):
        valid_refs = []
        for ref in getattr(item, "evidence", []):
            ref_id = str(ref.source_record_id).strip()

            # 1. Source record exists in our DB input context
            if ref_id not in input_source_ids:
                errors.append(
                    ValidationError(
                        message=f"Hallucinated or invalid source_record_id: '{ref_id}' not in extraction context",
                        item_title=getattr(item, "title", "Untitled"),
                        source_record_id=ref_id,
                        severity="error",
                    )
                )
                continue

            source = source_records_by_id.get(ref_id)
            if not source:
                errors.append(
                    ValidationError(
                        message=f"Source record '{ref_id}' could not be resolved from DB lookup",
                        item_title=getattr(item, "title", "Untitled"),
                        source_record_id=ref_id,
                        severity="error",
                    )
                )
                continue

            # 2. Excerpt check (fuzzy / case-insensitive)
            body = getattr(source, "body", "") or getattr(source, "body_text", "") or ""
            if ref.excerpt and body:
                if ref.excerpt.lower().strip() not in body.lower():
                    errors.append(
                        ValidationError(
                            message=f"Excerpt not found verbatim in source record {ref_id}",
                            item_title=getattr(item, "title", "Untitled"),
                            source_record_id=ref_id,
                            severity="warning",
                        )
                    )

            # 3. Check restricted flag
            is_restricted = False
            sensitivity = getattr(source, "sensitivity", None)
            if sensitivity and (sensitivity == Sensitivity.RESTRICTED or getattr(sensitivity, "value", "") == "RESTRICTED"):
                is_restricted = True

            setattr(ref, "is_restricted", is_restricted)
            valid_refs.append(ref)

        item.evidence = valid_refs
        # Only degrade to UNKNOWN if zero valid citations remain
        if not valid_refs and getattr(item, "evidence_state", None) != EvidenceState.UNKNOWN:
            item.evidence_state = EvidenceState.UNKNOWN

    # Validate items across all transfer packs
    for pack in result.transfer_packs:
        for claim_list_name in [
            "work_items",
            "decisions",
            "dependencies",
            "risks",
            "operational_notes",
            "knowledge_gaps",
            "next_actions",
        ]:
            for item in getattr(pack, claim_list_name, []):
                _validate_claim(item)

    # Validate unassigned items and cross-cutting items
    for item in result.unassigned_items:
        _validate_claim(item)
    for item in result.cross_cutting_risks:
        _validate_claim(item)
    for item in result.cross_cutting_gaps:
        _validate_claim(item)

    return result, errors
