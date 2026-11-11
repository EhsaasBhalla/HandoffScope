"""Phase 1 (Gap 1) tests: bounded relevance context, doc chunking, mock doc handling, and provider observability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import httpx

from app.db.enums import SourceRecordType
from app.integrations.documents import build_document_section_chunks
from app.integrations.llm.gemini_provider import GeminiProvider
from app.integrations.llm.mock_provider import MockLLMProvider
from app.integrations.llm.prompts.extraction_v1 import (
    SYSTEM_PROMPT,
    build_extraction_context,
    estimate_tokens,
    select_relevant_source_records,
)
from app.integrations.llm.schemas.extraction import ExtractionResult
from app.integrations.llm.validators import validate_extraction_result
from app.modules.ingestion.models import SourceRecord


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _make_record(
    *,
    rtype: SourceRecordType,
    ext_id: str,
    title: str,
    body: str,
    state: str = "closed",
    author: str = "arjun_patel",
    days_ago: int = 1,
    meta: dict | None = None,
    src_id: uuid.UUID | None = None,
) -> SourceRecord:
    ts = NOW - timedelta(days=days_ago)
    return SourceRecord(
        id=uuid.uuid4(),
        connected_source_id=src_id or uuid.UUID("11111111-1111-1111-1111-111111111111"),
        source_type="DOCUMENT_UPLOAD" if rtype == SourceRecordType.DOCUMENT_SECTION else "GITHUB_REPO",
        record_type=rtype,
        external_id=ext_id,
        title=title,
        body=body,
        state=state,
        author_external_id=author,
        author_name=author,
        external_created_at=ts,
        external_updated_at=ts,
        created_at=ts,
        metadata_json=meta,
    )


def test_context_selection_preserves_old_decisions_dedups_prs_and_respects_budget():
    src_id = uuid.uuid4()
    old_decision = _make_record(
        rtype=SourceRecordType.ISSUE,
        ext_id="5",
        title="ADR: Architecture Decision for Multi-Tenant Auth Token Rationale",
        body="Decision: We decided to isolate tenant tokens with KMS signing keys because cross-tenant isolation is critical.",
        state="open",
        days_ago=180,
        src_id=src_id,
    )
    pr_42 = _make_record(
        rtype=SourceRecordType.PR,
        ext_id="42",
        title="feat: JWT middleware (#5)",
        body="Implements JWT middleware.\n\nCloses #5\n\n" + ("Detailed diff summary line. " * 250),
        state="merged",
        days_ago=2,
        src_id=src_id,
    )
    dup_issue_42 = _make_record(
        rtype=SourceRecordType.ISSUE,
        ext_id="42",
        title="feat: JWT middleware (#5)",
        body="Duplicate PR-shaped issue from /issues endpoint.",
        state="closed",
        days_ago=2,
        meta={"is_pull_request": True},
        src_id=src_id,
    )

    records = [old_decision, pr_42, dup_issue_42]
    # Flood with 60 newer routine commits
    for idx in range(60):
        records.append(
            _make_record(
                rtype=SourceRecordType.COMMIT,
                ext_id=f"sha-{idx:03d}",
                title=f"chore: formatting tweak {idx}",
                body=f"Routine whitespace cleanup step {idx}",
                state="none",
                author="other_dev",
                days_ago=1,
                src_id=src_id,
            )
        )

    selected1, diag1 = select_relevant_source_records(
        records,
        case_title="Auth Service Handover",
        departing_identifiers={"arjun_patel"},
        max_records=15,
        max_token_budget=6000,
        excerpt_char_limit=600,
    )
    selected2, _ = select_relevant_source_records(
        list(reversed(records)),
        case_title="Auth Service Handover",
        departing_identifiers={"arjun_patel"},
        max_records=15,
        max_token_budget=6000,
        excerpt_char_limit=600,
    )

    selected_ids = {r.id for r in selected1}
    # Deterministic selection regardless of input ordering
    assert [r.id for r in selected1] == [r.id for r in selected2]
    # Duplicate ISSUE #42 excluded while PR #42 preserved
    assert dup_issue_42.id not in selected_ids
    assert pr_42.id in selected_ids
    assert diag1["deduplicated_pr_issues"] == 1
    # Older critical decision preserved even amidst 60 recent commits
    assert old_decision.id in selected_ids
    assert len(selected1) <= 15
    assert diag1["estimated_prompt_tokens"] <= 6000

    # Prompt excerpt bounded while DB body remains untouched
    prompt_ctx = build_extraction_context([pr_42], max_chars_per_record=600)
    assert len(prompt_ctx) < len(pr_42.body)
    assert len(pr_42.body) > 5000
    assert estimate_tokens(prompt_ctx) >= len(prompt_ctx) // 3


def test_mock_provider_handles_documents_adr_runbook_descriptive_and_empty():
    runbook_doc = _make_record(
        rtype=SourceRecordType.DOCUMENT_SECTION,
        ext_id="doc-runbook",
        title="auth_deploy_runbook.md",
        body="# Staging Deployment Procedure\nRun `./scripts/deploy-staging.sh` and verify `/health` responds 200 OK before rollout.",
        meta={"sections": build_document_section_chunks(None, "# Staging Deployment Procedure\nRun `./scripts/deploy-staging.sh` and verify `/health` responds 200 OK before rollout.")},
    )
    adr_doc = _make_record(
        rtype=SourceRecordType.DOCUMENT_SECTION,
        ext_id="doc-adr",
        title="adr_003_database.md",
        body="# ADR 003\nDecision: Use PostgreSQL JSONB for version snapshots because schema migrations stay reversible.",
        meta={"sections": build_document_section_chunks(None, "# ADR 003\nDecision: Use PostgreSQL JSONB for version snapshots because schema migrations stay reversible.")},
    )
    descriptive_doc = _make_record(
        rtype=SourceRecordType.DOCUMENT_SECTION,
        ext_id="doc-desc",
        title="team_onboarding_notes.txt",
        body="The engineering team holds weekly sync calls on Tuesdays and keeps onboarding notes in Notion.",
    )
    empty_doc = _make_record(
        rtype=SourceRecordType.DOCUMENT_SECTION,
        ext_id="doc-empty",
        title="blank_file.txt",
        body="   ",
    )

    all_recs = [runbook_doc, adr_doc, descriptive_doc, empty_doc]
    ctx = build_extraction_context(all_recs)
    provider = MockLLMProvider()
    result, meta = provider.extract_structured(SYSTEM_PROMPT, ctx, ExtractionResult)

    assert meta["provider_mode"] == "mock"
    assert meta["fallback_used"] is False

    validated, _ = validate_extraction_result(
        result,
        {str(r.id) for r in all_recs},
        {str(r.id): r for r in all_recs},
    )

    all_op_notes = [n for p in validated.transfer_packs for n in p.operational_notes]
    all_decisions = [d for p in validated.transfer_packs for d in p.decisions]
    all_evidence_ids = {
        ev.source_record_id
        for p in validated.transfer_packs
        for lst in (p.work_items, p.decisions, p.operational_notes, p.risks, p.knowledge_gaps, p.next_actions)
        for item in lst
        for ev in item.evidence
    }

    assert str(runbook_doc.id) in all_evidence_ids
    assert str(adr_doc.id) in all_evidence_ids
    assert str(empty_doc.id) not in all_evidence_ids  # Empty document never fabricated

    # Runbook produces operational note with locator; ADR produces decision
    assert any("auth_deploy_runbook.md" in n.title for n in all_op_notes)
    assert any("adr_003_database.md" in d.title for d in all_decisions)
    # Descriptive text without decision/rationale must NOT become a fabricated Decision
    assert not any("team_onboarding_notes.txt" in d.title for d in all_decisions)


def test_gemini_provider_bounded_retry_no_validation_retry_and_explicit_fallback(monkeypatch):
    rec = _make_record(
        rtype=SourceRecordType.PR,
        ext_id="77",
        title="feat: resilient retry",
        body="Adds retry handling for upstream HTTP 429.",
        state="merged",
    )
    ctx = build_extraction_context([rec])

    # Case A: Transient 429 retries bounded times then succeeds
    calls = {"count": 0}

    def fake_post_transient(url, headers=None, json=None, timeout=None):
        calls["count"] += 1
        assert "key=" not in url  # API key never placed in URL
        if calls["count"] < 2:
            return httpx.Response(429, headers={"Retry-After": "0.1"}, text="rate limited")
        sample_result = {
            "transfer_packs": [{
                "name": "Core Platform",
                "description": "Test",
                "work_items": [{
                    "title": "Retry logic",
                    "description": "Adds retry",
                    "current_state": "completed",
                    "evidence_state": "SUPPORTED",
                    "evidence": [{"source_record_id": str(rec.id), "excerpt": "Adds retry handling", "relevance": "direct"}],
                }],
            }]
        }
        import json as _json
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": _json.dumps(sample_result)}]}}]})

    monkeypatch.setattr(httpx, "post", fake_post_transient)
    provider = GeminiProvider(api_key="dummy-key", model_name="gemini-3.5-flash", timeout_seconds=15.0, max_retries=2)
    res, meta = provider.extract_structured(SYSTEM_PROMPT, ctx, ExtractionResult)
    assert calls["count"] == 2
    assert meta["provider_mode"] == "live"
    assert meta["fallback_used"] is False
    assert len(res.transfer_packs) == 1

    # Case B: Validation/JSON errors do NOT retry multiple times per model, and fallback is explicitly labeled
    invalid_calls = {"count": 0}

    def fake_post_bad_json(url, headers=None, json=None, timeout=None):
        invalid_calls["count"] += 1
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "NOT VALID JSON"}]}}]})

    monkeypatch.setattr(httpx, "post", fake_post_bad_json)
    provider2 = GeminiProvider(api_key="dummy-key", model_name="gemini-3.5-flash", max_retries=2)
    res2, meta2 = provider2.extract_structured(SYSTEM_PROMPT, ctx, ExtractionResult)
    # 4 candidate models, 1 call each (zero retries on JSON parse failure!)
    assert invalid_calls["count"] == 4
    assert meta2["provider_mode"] == "mock_fallback"
    assert meta2["fallback_used"] is True
    assert "validation error" in (meta2["fallback_reason"] or "").lower()
    assert meta2["model_used"] == "mock-extraction-v1"

    # Case C: Unescaped raw newlines inside string OR truncated JSON tail (Unterminated string) recovers cleanly
    raw_newline_json = (
        '{\n'
        '  "transfer_packs": [{\n'
        '    "name": "Core Platform",\n'
        '    "description": "Test multiline\nnewline inside JSON string",\n'
        '    "work_items": [{\n'
        '      "title": "Retry logic",\n'
        '      "description": "Adds retry handling",\n'
        '      "current_state": "completed",\n'
        '      "evidence_state": "SUPPORTED",\n'
        '      "evidence": [{"source_record_id": "' + str(rec.id) + '", "excerpt": "Adds retry handling", "relevance": "direct"}]\n'
        '    },\n'
        '    {\n'
        '      "title": "Truncated second item cut off mid string'
    )

    def fake_post_truncated(url, headers=None, json=None, timeout=None):
        assert json["generationConfig"]["maxOutputTokens"] == 16384
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": raw_newline_json}]}}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post_truncated)
    provider3 = GeminiProvider(api_key="dummy-key", model_name="gemini-3.5-flash", max_retries=2)
    res3, meta3 = provider3.extract_structured(SYSTEM_PROMPT, ctx, ExtractionResult)
    assert meta3["provider_mode"] == "live"
    assert meta3["fallback_used"] is False
    assert len(res3.transfer_packs) == 1
    assert len(res3.transfer_packs[0].work_items) == 1

    # Case D: Q&A truncated mid-answer_text still recovers partial valid answer & uses 8192 maxOutputTokens
    qa_trunc = '{"answer_text": "Run pg_ctl promote on standby\nline2", "answer_status": "answered", "limitations": "Still writing'
    qa_calls = {"count": 0}

    def fake_post_qa_truncated(url, headers=None, json=None, timeout=None):
        qa_calls["count"] += 1
        assert json["generationConfig"]["maxOutputTokens"] == 8192
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": qa_trunc}]}}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post_qa_truncated)
    from app.integrations.llm.schemas.qa import QuestionAnswerResult
    qa_res, qa_meta = provider3.answer_question("sys", "usr", QuestionAnswerResult)
    assert qa_calls["count"] == 1
    assert qa_meta["provider_mode"] == "live"
    assert "pg_ctl promote" in qa_res.answer_text

    # Case E: Unrecoverable MAX_TOKENS truncation retries once with doubled maxOutputTokens then succeeds
    retry_trunc = {"count": 0}

    def fake_post_expand_tokens(url, headers=None, json=None, timeout=None):
        retry_trunc["count"] += 1
        if retry_trunc["count"] == 1:
            assert json["generationConfig"]["maxOutputTokens"] == 16384
            return httpx.Response(
                200,
                json={"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"transfer_packs": [{"na'}]}}]},
            )
        assert json["generationConfig"]["maxOutputTokens"] == 32768
        good = {
            "transfer_packs": [{
                "name": "Recovered",
                "description": "Succeeded after expanding output token budget",
                "work_items": [{
                    "title": "Valid Item",
                    "description": "Recovered",
                    "current_state": "open",
                    "evidence_state": "SUPPORTED",
                    "evidence": [{"source_record_id": str(rec.id), "excerpt": "Adds retry handling", "relevance": "direct"}],
                }],
            }]
        }
        import json as _json
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": _json.dumps(good)}]}}]})

    monkeypatch.setattr(httpx, "post", fake_post_expand_tokens)
    res4, meta4 = provider3.extract_structured(SYSTEM_PROMPT, ctx, ExtractionResult)
    assert retry_trunc["count"] == 2
    assert meta4["provider_mode"] == "live"
