# HandoffScope — Comprehensive Architecture Gap Remediation Plan

> **Document Status:** Planning & Design Phase  
> **Directive:** Strictly plan all fixes without modifying application code until explicit user approval.  
> **Guiding Principle:** Zero regressions on existing passing test suites (36 tests) and production Vite build. Maintain absolute evidence-grounded integrity.

---

## 1. Executive Summary & Remediation Principles

During the comprehensive audit of the **HandoffScope** full-stack platform (FastAPI, React 19, PostgreSQL, Google Gemini 3.5-flash / Mock fallback), six architectural and functional gaps were identified across the knowledge reconstruction pipeline, interactive Q&A loop, review gates, and recipient projections.

This document details the architectural blueprints, risk assessments, test strategies, and implementation steps to remediate all six gaps safely.

### Non-Negotiable Engineering Constraints
1. **Zero Regressions:** All 36 existing backend tests (`pytest tests/ -q`) and frontend compilation (`npm run build`) must pass without failure after every phase.
2. **Deterministic Fallbacks:** The platform must function with 100% feature parity whether running live with a valid Google Gemini API key or in offline/mock mode (`MockLLMProvider`).
3. **Strict Evidence Grounding:** No claim or question response may be generated without verified citation anchors to existing `SourceRecord` UUIDs. Hallucinated or orphaned references are rejected by schema validators.
4. **Frozen Immutability:** Approved handover versions (`HandoverVersion`) must remain tamper-proof historical snapshots that cannot be mutated by subsequent draft edits or re-extractions.

---

## 2. Gap 1 — Context Window Overload & Document Ingestion in Mock LLM

### 2.1 Problem Description & Root Cause
- **Live Mode:** In `backend/app/modules/reconstruction/service.py`, the query pulls up to 150 `SourceRecord` entries without truncating large message bodies or file contents. In real-world repositories with 100+ commits and large document sections (e.g., architecture PDFs or API specs), the assembled prompt easily exceeds 250,000 characters, triggering Gemini free-tier rate limits (RPM/TPM) or request timeouts (currently 30s in `gemini_provider.py`). When Gemini fails, it silently falls back to `MockLLMProvider`.
- **Mock Mode:** In `backend/app/integrations/llm/mock_provider.py` (lines 123–156), the mock extraction loop only inspects `r["type"] in ["ISSUE", "PR"]` and `r["type"] == "COMMIT"`. It has **no branch for `DOCUMENT_SECTION`** or `DOCUMENT`. Consequently, uploaded documents bridged from the Document Ingestion pipeline are completely ignored during mock extraction, creating an impression that document uploads are broken.

### 2.2 Impact
- Real-world GitHub repositories with lengthy PR descriptions or large commits fail with timeout/quota errors.
- Document uploads appear to produce zero claims in test environments or when running against the mock provider.

### 2.3 Proposed Solution Architecture
1. **Context Window Bounding & Prioritization (`reconstruction/service.py` & `extraction_v1.py`):**
   - Implement intelligent context truncation in `build_extraction_context`: limit individual record bodies to **1,200 characters** (retaining title, author, date, state, and relevant body excerpt).
   - Apply a diversity-aware record sampling: cap total records sent to the LLM at **50 records** maximum, prioritizing:
     - Up to 15 recent closed/merged PRs
     - Up to 15 open/active Issues
     - Up to 10 latest Commits
     - Up to 10 Document Sections (architecture/runbooks)
   - Increase Gemini HTTP client timeout from 30 seconds to **60 seconds** to accommodate complex multi-pack synthesis.
2. **Document Record Handling in `MockLLMProvider` (`mock_provider.py`):**
   - Add explicit handling for `r["type"] in ["DOCUMENT_SECTION", "DOCUMENT"]`.
   - Map document sections into `ExtractedOperationalNote` (for runbooks, deployment guides) and `ExtractedDecision` (for architecture docs, ADRs), with valid citations linking to the document's `SourceRecord` UUID.

### 2.4 Files to Modify
- `backend/app/integrations/llm/prompts/extraction_v1.py` (`build_extraction_context`)
- `backend/app/modules/reconstruction/service.py` (diversity sampling & record limits)
- `backend/app/integrations/llm/gemini_provider.py` (timeout configuration)
- `backend/app/integrations/llm/mock_provider.py` (add document section mapping)

### 2.5 Risk Assessment & Mitigation
- **Risk:** Truncating bodies could omit critical details needed for fine-grained claim extraction.
- **Mitigation:** Retain the first 1,000 characters + last 200 characters of each record body, capturing both the problem statement and the resolution/merge commit notes.

---

## 3. Gap 2 — AI-Generated Grounded Evidence Answers for Handover Questions

### 3.1 Problem Description & Root Cause
- The Questions module (`app/modules/questions/`) currently supports a human-to-human communication loop: a successor or reviewer posts a question, and an assigned departing engineer manually types an answer.
- However, when a successor or judge asks an operational question (e.g., *"How is user authentication configured?"* or *"What are the known failure modes in the sync pipeline?"*), the system does not offer an AI-assisted answer generator grounded in the ingested source records and reconstructed transfer packs.

### 3.2 Impact
- Successors cannot immediately query the institutional memory captured by HandoffScope; they must wait for human intervention.
- Judges evaluating the deployment link cannot test autonomous knowledge retrieval from the uploaded sources.

### 3.3 Proposed Solution Architecture
1. **New Backend Endpoint:**
   - `POST /api/v1/questions/{question_id}/generate-answer`
   - **Service Function:** `generate_ai_question_answer(db: Session, question_id: uuid.UUID, user_id: uuid.UUID) -> QuestionResponseOut`
2. **Grounded Retrieval Mechanism:**
   - Retrieve the question text and `why_it_matters`.
   - Identify candidate context from the question's `case_id`:
     - Matched `Claim` records from existing Transfer Packs (matching keywords or pack category).
     - Relevant `SourceRecord` entries (commits, PRs, issues, document sections).
   - Format a focused LLM prompt:
     - Prompt instructs the LLM to formulate a clear, authoritative response based **strictly** on the provided excerpts.
     - Mandates inline citations to the supporting `SourceRecord` or `Claim` IDs.
     - If the context does not contain the answer, explicitly output an admission of knowledge gap with suggested follow-up areas.
3. **Storage & Audit:**
   - Create a `QuestionResponse` record with:
     - `respondent_id`: Set to the requesting user or system agent.
     - `response_text`: AI-generated answer with cited evidence IDs.
     - `review_state`: Set to `PENDING_REVIEW` (allowing the reviewer/lead to verify and accept).
   - Update `question.status` to `ANSWERED`.
   - Write an audit event `question.ai_answer_generated`.
4. **Mock Provider Support:**
   - Add `generate_question_answer(question_text, context_records)` in `MockLLMProvider` returning a structured, grounded answer using the provided mock records.
5. **Frontend UI Enhancement:**
   - In `frontend/src/pages/questions/questions.jsx` and `handover-case-detail.jsx`:
     - Add a "✨ Generate AI Draft Answer" button on open question cards.
     - Displays a loading spinner while generating, then surfaces the generated response in the thread with an "AI Suggested Answer — Grounded in Repository Evidence" badge.

### 3.4 Files to Modify / Create
- `backend/app/modules/questions/router.py` (add `POST /questions/{id}/generate-answer`)
- `backend/app/modules/questions/service.py` (implement `generate_ai_question_answer`)
- `backend/app/integrations/llm/prompts/question_answering_v1.py` (new prompt template)
- `backend/app/integrations/llm/gemini_provider.py` & `mock_provider.py` (method `generate_question_answer`)
- `frontend/src/api/question.api.js` (add `generateAiAnswer(questionId)`)
- `frontend/src/pages/questions/questions.jsx` (UI trigger button & badge)

### 3.5 Risk Assessment & Mitigation
- **Risk:** AI might hallucinate an answer not present in the ingested repository.
- **Mitigation:** The system prompt enforces strict refusal if source evidence is absent, and the generated response is saved as `PENDING_REVIEW`, requiring human reviewer sign-off before being promoted to verified knowledge.

---

## 4. Gap 3 — Promoting Accepted Question Answers into Transfer Pack Claims

### 4.1 Problem Description & Root Cause
- When a question answer is reviewed and accepted via `PATCH /api/v1/questions/{question_id}/review` (action: `"accept"`), `questions/service.py:review_response` sets `question.status = RESOLVED` and `target_response.review_state = ACCEPTED`.
- However, this newly clarified knowledge **remains trapped in the questions table**.
- If the question was linked to an existing claim in `NEEDS_CLARIFICATION` status (`question.claim_id`), that claim is **not updated or unblocked**.
- If the question was a standalone inquiry revealing a new operational note or architecture decision, **no claim is added to the Transfer Pack**.

### 4.2 Impact
- Claims marked `NEEDS_CLARIFICATION` indefinitely block version approval even after the engineer has answered the question and the reviewer has accepted the answer.
- Critical tribal knowledge discovered through Q&A never reaches the successor's generated Transfer Pack or final handover PDF.

### 4.3 Proposed Solution Architecture
1. **Unblocking Linked Clarification Claims:**
   - In `questions/service.py:review_response`, when `action == "accept"`:
     - Check if `question.claim_id` is populated.
     - If yes, query the linked `Claim`:
       - If `claim.review_state == ReviewState.NEEDS_CLARIFICATION`:
         - Transition `claim.review_state = ReviewState.EDITED_AND_ACCEPTED` (or `PENDING_REVIEW`).
         - Append the accepted answer text to `claim.body_text` under an `--- ACCEPTED CLARIFICATION (Date: ...) ---` section.
         - Update `claim.evidence_state = EvidenceState.SUPPORTED`.
         - Log an audit event `claim.clarified_from_question`.
2. **Promoting Standalone Q&A to New Transfer Pack Claims:**
   - If `question.claim_id` is null, but `question.transfer_pack_id` is set (or the case has an active Transfer Pack):
     - Automatically create a new `Claim`:
       - `claim_type`: `ClaimType.OPERATIONAL_NOTE` (or `DECISION` if tagged as architecture).
       - `title`: `f"Clarification: {question.question_text[:80]}"`
       - `body_text`: `target_response.response_text`
       - `review_state`: `ReviewState.ACCEPTED`
       - `evidence_state`: `EvidenceState.SUPPORTED`
       - Associate a `ClaimEvidence` linking back to the question and any cited source records.
       - Link `question.claim_id = new_claim.id`.
3. **Frontend Feedback:**
   - Toast notification: *"Question accepted and knowledge successfully promoted into Transfer Pack!"*

### 4.4 Files to Modify
- `backend/app/modules/questions/service.py` (`review_response`)
- `backend/tests/api/test_core_pipeline_regressions.py` (add regression test verifying claim unblocking on question acceptance)

### 4.5 Risk Assessment & Mitigation
- **Risk:** Creating duplicate claims if a question is amended and re-accepted.
- **Mitigation:** Check if `question.claim_id` already exists before creating a new claim; if it already exists, update the existing claim in place rather than inserting a duplicate.

---

## 5. Gap 4 — Successor View Reading Frozen Snapshots vs Live Mutable DB

### 5.1 Problem Description & Root Cause
- In `backend/app/modules/recipients/service.py:build_recipient_projection`:
  - The endpoint checks if a current `HandoverVersion` exists.
  - However, in lines 224–250, it queries live database tables:
    ```python
    packs = db.query(TransferPack).filter(TransferPack.case_id == case_id).all()
    for p in packs:
        claims = db.query(Claim).filter(Claim.transfer_pack_id == p.id).all()
    ```
- This directly violates the immutability guarantee: if someone edits or deletes a claim in a draft state after Version 1 is approved, or triggers a re-extraction, those unapproved, in-flight changes immediately leak into the successor's view.

### 5.2 Impact
- Successors see unstable, unapproved draft changes rather than the legally approved, signed-off version.
- Violates enterprise compliance requirements for audit-proof knowledge handovers.

### 5.3 Proposed Solution Architecture
1. **Snapshot-First Projection Logic in `build_recipient_projection`:**
   - If `current_version` exists AND `current_version.snapshot_json` is not empty:
     - Parse `packs` and `claims` directly from `current_version.snapshot_json["transfer_packs"]`.
     - Extract `next_actions`, `unfinished_items`, and `access_blockers` from the frozen snapshot.
   - If no approved version exists (case is still in DRAFT or RECONSTRUCTED):
     - Fall back to the live database query so the successor or reviewer can preview work-in-progress before formal approval.
2. **Dynamic Overlay Preservation:**
   - Keep dynamic, post-approval interactions live on top of the frozen snapshot:
     - `ResponsibilityAssignment` records (assignments can be acknowledged or transferred post-approval).
     - `RecipientAcknowledgement` status (sign-off timestamp and notes).
     - Restricted evidence redaction (mask restricted URLs/bodies based on viewer's clearance level).

### 5.4 Files to Modify
- `backend/app/modules/recipients/service.py` (`build_recipient_projection`)
- `backend/tests/api/test_core_pipeline_regressions.py` (add test verifying that draft edits after version creation do not alter the successor view)

### 5.5 Risk Assessment & Mitigation
- **Risk:** Older snapshot JSON schemas might lack certain fields expected by newer frontend versions.
- **Mitigation:** Use defensive `.get(field, default)` lookups when parsing `snapshot_json` with graceful fallbacks.

---

## 6. Gap 5 — Review Queue Approval Guardrails & Blocker Checks

### 6.1 Problem Description & Root Cause
- In `backend/app/modules/reviews/service.py`:
  - `get_review_queue_summary` checks pending, rejected, and clarification claims.
  - However, it **does not verify whether the case has unresolved open blocking questions** (`QuestionStatus.OPEN` or `QuestionStatus.NEEDS_CLARIFICATION`).
  - It also does not inspect the case's `case.is_blocked` flag.
  - Furthermore, `create_approved_version` lacks an explicit parameter allowing a designated Lead/Admin to record an override justification if non-critical questions remain open.

### 6.2 Impact
- A reviewer could prematurely approve a version while critical questions regarding production credentials, architecture decisions, or pending migrations are still open and unanswered.

### 6.3 Proposed Solution Architecture
1. **Enhanced Pre-Flight Checks in `get_review_queue_summary`:**
   - Query open questions:
     ```python
     open_questions = db.query(Question).filter(
         Question.case_id == case_id,
         Question.status.in_([QuestionStatus.OPEN, QuestionStatus.ANSWERED])
     ).count()
     ```
   - If `open_questions > 0`:
     - Add blocking reason: `f"{open_questions} question(s) remain open or awaiting review."`
   - If `case.is_blocked`:
     - Add blocking reason: `"Handover Case is flagged as blocked by an active impediment."`
2. **Controlled Reviewer Override in `create_approved_version`:**
   - Allow an optional parameter `override_blockers: bool = False` and `override_reason: Optional[str] = None`.
   - If blockers exist and `override_blockers` is `False`, reject with HTTP 400 listing exact reasons.
   - If `override_blockers` is `True`, require `override_reason` (min 10 characters), transition the case, and record an audit log entry: `handover_version.approved_with_override`.
3. **Frontend UI State:**
   - In `frontend/src/pages/review-queue/review-queue.jsx`, display the count of open questions alongside pending claims in the "Pre-Flight Checklist" card.
   - If blockers exist, disable the "Approve & Seal Version" button with a clear tooltip. If the user is Lead, show an "Override & Approve (with Justification)" dialog.

### 6.4 Files to Modify
- `backend/app/modules/reviews/service.py` (`get_review_queue_summary`, `create_approved_version`)
- `backend/app/modules/reviews/router.py` (support override schema)
- `backend/app/modules/reviews/schemas.py` (add `override_blockers`, `override_reason`)
- `frontend/src/pages/review-queue/review-queue.jsx` (display open questions in pre-flight checks)

### 6.5 Risk Assessment & Mitigation
- **Risk:** Existing tests calling `create_approved_version` might fail if demo seed cases have lingering open questions.
- **Mitigation:** In test fixtures and demo seed scripts, ensure questions on approved cases are seeded in `RESOLVED` status, or pass `override_blockers=True` where appropriate.

---

## 7. Gap 6 — Database Deduplication & Sync vs. Freshness Clarity

### 7.1 Problem Description & Root Cause
- **Historical Data Artifacts:** Prior to the fix in `client.py` and `mapper.py`, GitHub `/issues` endpoint synced Pull Requests as both `ISSUE` and `PR` records. While newly synced sources no longer create duplicate `ISSUE` records, environments that ran syncs before that fix may still retain duplicate source records.
- **UX Ambiguity:** In `frontend/src/pages/sources/sources.jsx`, users could be confused between:
  - **"Sync Repository":** Connects to GitHub API and imports new/updated commits, PRs, and issues.
  - **"Check Freshness":** Analyzes staleness (drift) of existing records against project timestamps without making outbound GitHub API calls.

### 7.2 Impact
- Duplicate records inflate claim counts and confuse users during evidence exploration.
- Users expecting "Check Freshness" to download new commits from GitHub wonder why new PRs do not appear.

### 7.3 Proposed Solution Architecture
1. **Deduplication Migration / Cleanup Script:**
   - Add a safe backend utility function `cleanup_duplicate_github_records(db: Session, project_id: uuid.UUID) -> int`:
     - Identifies `SourceRecord` entries with `record_type == 'ISSUE'` where an identical `external_id` exists with `record_type == 'PR'`.
     - Safely removes the duplicate `ISSUE` record after re-linking any `ClaimEvidence` references to the canonical `PR` record.
   - Expose this optionally via `POST /api/v1/sources/{source_id}/deduplicate` (restricted to Leads).
2. **Frontend UX Clarification in `sources.jsx`:**
   - Ensure the distinction is highlighted with contextual tooltips:
     - **Sync Repository:** *"Pulls latest commits, PRs, issues, and releases from remote GitHub repository."*
     - **Check Freshness:** *"Evaluates repository drift and identifies stale documentation without re-fetching."*

### 7.4 Files to Modify
- `backend/app/modules/sources/service.py` (add deduplication utility)
- `backend/app/modules/sources/router.py` (expose cleanup endpoint)
- `frontend/src/pages/sources/sources.jsx` (clarify button tooltips and labels)

---

## 8. Phased Implementation Sequence & Safety Gates

To guarantee that no running feature is broken during execution, changes will be implemented in four sequential phases, each followed by test verification:

```mermaid
flowchart TD
    subgraph Phase 1: Ingestion & Extraction Robustness
        A1[1. Context Bounding in extraction_v1.py] --> A2[2. MockLLMProvider Document Handling]
        A2 --> A3[Verify: pytest tests/unit/test_ai_pipeline.py]
    end

    subgraph Phase 2: Q&A AI Engine & Claim Promotion
        B1[1. Add AI Answer Endpoint in questions/] --> B2[2. Unblock Claims on Response Acceptance]
        B2 --> B3[Verify: pytest tests/api/test_core_pipeline_regressions.py]
    end

    subgraph Phase 3: Review Guardrails & Frozen Snapshots
        C1[1. Successor Projection from snapshot_json] --> C2[2. Pre-flight checks for open questions]
        C2 --> C3[Verify: pytest tests/api/test_judge_e2e_flow.py]
    end

    subgraph Phase 4: Frontend Alignment & E2E Validation
        D1[1. AI Answer Button in Questions UI] --> D2[2. Review Queue Pre-flight Visuals]
        D2 --> D3[Verify: npm run build & full test suite 36+ tests]
    end

    Phase 1 --> Phase 2
    Phase 2 --> Phase 3
    Phase 3 --> Phase 4
```

### Verification Command Gates
1. **Backend Tests:**
   ```powershell
   Set-Location "E:\CodeNexus\HandoffScope\backend"
   py -3.14 -m pytest tests/ -q
   ```
   *Requirement: 100% pass (36/36+ tests).*
2. **Frontend Build:**
   ```powershell
   Set-Location "E:\CodeNexus\HandoffScope\frontend"
   npm run build
   ```
   *Requirement: Clean compilation with 0 errors.*

---

## 9. Conclusion & Next Step
This remediation plan addresses every identified vulnerability and architectural limitation while protecting the integrity of the deployed platform. 

**Awaiting user review and approval before writing or editing any application code.**
