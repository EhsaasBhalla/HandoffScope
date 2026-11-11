"""Mock LLM Provider for automated tests, demonstrations, and offline operation.

Parses actual source records from prompt context to generate 100% grounded Transfer Packs
and evidence-grounded question drafts without inventing ungrounded records.
"""

from __future__ import annotations

import re
import time
from typing import Any, Type

from pydantic import BaseModel

from app.integrations.llm.base import LLMProvider
from app.integrations.llm.schemas.extraction import (
    CandidateTransferPack,
    EvidenceReference,
    EvidenceState,
    ExtractedDecision,
    ExtractedDependency,
    ExtractedKnowledgeGap,
    ExtractedNextAction,
    ExtractedOperationalNote,
    ExtractedQuestionSuggestion,
    ExtractedRisk,
    ExtractedWorkItem,
    ExtractionResult,
)
from app.integrations.llm.schemas.qa import QAEvidenceReference, QuestionAnswerResult


def _clean_verbatim_excerpt(raw_body: str, max_len: int = 160) -> tuple[str, str | None]:
    """Strip prompt locator prefixes and truncation markers so excerpts verify verbatim."""
    locator: str | None = None
    lines = []
    for line in raw_body.splitlines():
        m = re.match(r"^\[(Page \d+|Section: [^\]]+)\]$", line.strip())
        if m:
            if not locator:
                locator = m.group(1)
            continue
        if "...[excerpt truncated" in line:
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        return "", locator
    excerpt = cleaned[:max_len].strip()
    return excerpt, locator


def parse_prompt_source_records(user_prompt: str) -> list[dict[str, str]]:
    """Extract structured source record metadata and bodies from delimited prompt blocks."""
    block_pattern = re.compile(
        r"--- SOURCE RECORD[^\n]*\n(.*?)\n--- END SOURCE RECORD ---",
        re.DOTALL,
    )
    records: list[dict[str, str]] = []
    for block_match in block_pattern.finditer(user_prompt):
        block = block_match.group(1)
        if "Content:\n" not in block:
            continue
        header_part, body_part = block.split("Content:\n", 1)
        headers: dict[str, str] = {}
        for line in header_part.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()

        rec_id = headers.get("ID", "").strip()
        if not rec_id:
            continue
        records.append({
            "id": rec_id,
            "type": headers.get("Type", "RECORD").strip().upper(),
            "title": headers.get("Title", "Untitled").strip(),
            "state": headers.get("State", "unknown").strip(),
            "author": headers.get("Author", "unknown").strip(),
            "timestamp": headers.get("Timestamp", "").strip(),
            "locator_hint": headers.get("LocatorHint", "").strip(),
            "external_id": headers.get("ExternalID", "").strip(),
            "body": body_part.strip(),
        })
    return records


class MockLLMProvider(LLMProvider):
    """Generates grounded extraction results from real source records in the prompt."""

    def __init__(self, model_name: str = "mock-extraction-v1"):
        self.model_name = model_name

    def get_model_name(self) -> str:
        return self.model_name

    def extract_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel],
        *,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> tuple[BaseModel, dict[str, Any]]:
        start_time = time.time()
        records = parse_prompt_source_records(user_prompt)

        if not records:
            result = ExtractionResult()
            return result, {
                "input_tokens": self.count_tokens(user_prompt),
                "output_tokens": 50,
                "latency_ms": max(1, int((time.time() - start_time) * 1000)),
                "provider_mode": "mock",
                "model_used": self.model_name,
                "fallback_used": False,
                "fallback_reason": None,
            }

        # Filter out empty/uninformative documents so mock does not fabricate claims for empty uploads
        substantive_records = [
            r
            for r in records
            if not (
                r["type"] in {"DOCUMENT_SECTION", "DOCUMENT"}
                and (not r["body"] or r["body"].lower() == "no body content" or len(r["body"].strip()) < 12)
            )
        ]
        if not substantive_records:
            result = ExtractionResult()
            return result, {
                "input_tokens": self.count_tokens(user_prompt),
                "output_tokens": 60,
                "latency_ms": max(1, int((time.time() - start_time) * 1000)),
                "provider_mode": "mock",
                "model_used": self.model_name,
                "fallback_used": False,
                "fallback_reason": None,
            }

        # Group records into domain packs cleanly
        pack_groups: dict[str, list[dict[str, str]]] = {
            "Core Architecture & Infrastructure": [],
            "Feature Services & Integrations": [],
            "Operations, Runbooks & Quality": [],
        }

        for rec in substantive_records:
            title_lower = rec["title"].lower()
            body_lower = rec["body"].lower()
            if any(k in title_lower or k in body_lower for k in ("auth", "security", "core", "database", "schema", "model", "adr", "architecture")):
                pack_groups["Core Architecture & Infrastructure"].append(rec)
            elif any(k in title_lower or k in body_lower for k in ("deploy", "docker", "test", "ci", "bug", "fix", "runbook", "ops", "rollback", "backup")):
                pack_groups["Operations, Runbooks & Quality"].append(rec)
            else:
                pack_groups["Feature Services & Integrations"].append(rec)

        transfer_packs: list[CandidateTransferPack] = []

        for pack_name, recs in pack_groups.items():
            if not recs:
                continue

            work_items: list[ExtractedWorkItem] = []
            decisions: list[ExtractedDecision] = []
            dependencies: list[ExtractedDependency] = []
            risks: list[ExtractedRisk] = []
            operational_notes: list[ExtractedOperationalNote] = []
            knowledge_gaps: list[ExtractedKnowledgeGap] = []
            next_actions: list[ExtractedNextAction] = []
            question_suggestions: list[ExtractedQuestionSuggestion] = []

            # Balance selection across source types so documents/PRs/issues/commits are all represented
            doc_recs = [r for r in recs if r["type"] in {"DOCUMENT_SECTION", "DOCUMENT"}][:8]
            pr_issue_recs = [r for r in recs if r["type"] in {"ISSUE", "PR"}][:8]
            commit_recs = [r for r in recs if r["type"] == "COMMIT"][:4]
            selected_recs = doc_recs + pr_issue_recs + commit_recs

            for r in selected_recs:
                verbatim_excerpt, chunk_locator = _clean_verbatim_excerpt(r["body"])
                locator = chunk_locator or (r["locator_hint"] if r["locator_hint"] and r["locator_hint"] != "Full Record" else None)
                if not locator:
                    locator = f"External {r['type']} #{r['external_id'] or r['id'][:8]}"

                ref = EvidenceReference(
                    source_record_id=r["id"],
                    excerpt=verbatim_excerpt if verbatim_excerpt else r["title"],
                    locator=locator,
                    relevance=f"Primary source record from {r['author']}",
                )

                title_low = r["title"].lower()
                body_low = r["body"].lower()
                combined_low = f"{title_low} {body_low}"

                if r["type"] in {"ISSUE", "PR"}:
                    work_items.append(
                        ExtractedWorkItem(
                            title=f"Work on {r['title']}",
                            description=f"Status: {r['state']}. Authored by {r['author']}.",
                            current_state="completed" if r["state"].lower() in {"closed", "merged"} else "in_progress",
                            evidence_state=EvidenceState.SUPPORTED,
                            evidence=[ref],
                            related_source_record_ids=[r["id"]],
                            assigned_to=r["author"],
                            priority="HIGH" if any(k in title_low for k in ("fix", "critical", "blocker")) else "MEDIUM",
                        )
                    )
                elif r["type"] == "COMMIT":
                    decisions.append(
                        ExtractedDecision(
                            title=f"Implementation change: {r['title']}",
                            description=f"Code change recorded by {r['author']}.",
                            rationale=verbatim_excerpt[:120] if verbatim_excerpt else "Recorded in commit message",
                            author=r["author"],
                            evidence_state=EvidenceState.SUPPORTED,
                            evidence=[ref],
                        )
                    )
                elif r["type"] in {"DOCUMENT_SECTION", "DOCUMENT"}:
                    is_adr = any(k in combined_low for k in ("decision", "decided", "rationale", "trade-off", "tradeoff", "chosen", "adr"))
                    is_runbook = any(k in combined_low for k in ("runbook", "deploy", "procedure", "troubleshooting", "workaround", "rollback", "backup", "step "))
                    has_risk_or_gap = any(k in combined_low for k in ("risk", "warning", "manual", "missing", "not yet", "gap", "blocked"))

                    if is_adr:
                        decisions.append(
                            ExtractedDecision(
                                title=f"Documented decision in {r['title']}",
                                description=verbatim_excerpt or f"Decision and rationale captured in {r['title']}.",
                                rationale=verbatim_excerpt[:150] if verbatim_excerpt else None,
                                author=r["author"],
                                evidence_state=EvidenceState.SUPPORTED,
                                evidence=[ref],
                            )
                        )
                    if is_runbook or not is_adr:
                        cat = "runbook" if is_runbook else "procedure"
                        operational_notes.append(
                            ExtractedOperationalNote(
                                title=f"Documentation summary: {r['title']}",
                                description=verbatim_excerpt or f"Reference documentation from {r['title']}.",
                                category=cat,
                                evidence_state=EvidenceState.SUPPORTED,
                                evidence=[ref],
                            )
                        )
                    if has_risk_or_gap:
                        risks.append(
                            ExtractedRisk(
                                title=f"Documented operational risk in {r['title']}",
                                description=verbatim_excerpt or f"Operational risk noted in {r['title']}.",
                                evidence_state=EvidenceState.SUPPORTED,
                                evidence=[ref],
                            )
                        )

            # Anchor pack-level synthesis strictly in primary source evidence present
            anchor_rec = selected_recs[0]
            anchor_excerpt, anchor_loc = _clean_verbatim_excerpt(anchor_rec["body"], 120)
            sample_ref = EvidenceReference(
                source_record_id=anchor_rec["id"],
                excerpt=anchor_excerpt or anchor_rec["title"],
                locator=anchor_loc or f"External {anchor_rec['type']} #{anchor_rec['external_id'] or anchor_rec['id'][:8]}",
                relevance="Direct evidence from primary source record",
            )

            if any(k in (anchor_rec["body"] + " " + anchor_rec["title"]).lower() for k in ("depend", "require", "upstream", "api", "redis", "postgres", "payment")):
                dependencies.append(
                    ExtractedDependency(
                        title=f"{pack_name} upstream integration requirements",
                        description=f"Component dependencies referenced in '{anchor_rec['title']}'.",
                        dependency_type="requires",
                        source_component=pack_name,
                        evidence_state=EvidenceState.INFERRED,
                        evidence=[sample_ref],
                    )
                )

            if not risks and any(r["state"].lower() == "open" for r in selected_recs):
                open_rec = next(r for r in selected_recs if r["state"].lower() == "open")
                open_ex, _ = _clean_verbatim_excerpt(open_rec["body"], 120)
                open_ref = EvidenceReference(
                    source_record_id=open_rec["id"],
                    excerpt=open_ex or open_rec["title"],
                    locator=f"External {open_rec['type']} #{open_rec['external_id'] or open_rec['id'][:8]}",
                    relevance="Unresolved open item in repository",
                )
                risks.append(
                    ExtractedRisk(
                        title=f"Unresolved work risk: {open_rec['title']}",
                        description=f"Open {open_rec['type'].lower()} remains unresolved during handover.",
                        impact="Potential delay or ownership ambiguity until resolved",
                        mitigation="Confirm ownership and completion plan with successor",
                        evidence_state=EvidenceState.SUPPORTED,
                        evidence=[open_ref],
                    )
                )

            if not operational_notes:
                operational_notes.append(
                    ExtractedOperationalNote(
                        title=f"Operational notes for {pack_name}",
                        description=f"Verified operational details derived from '{anchor_rec['title']}'.",
                        category="procedure",
                        evidence_state=EvidenceState.INFERRED,
                        evidence=[sample_ref],
                    )
                )

            gap = ExtractedKnowledgeGap(
                title=f"Verify production status for {anchor_rec['title']}",
                description="Explicit production runtime sign-off should be confirmed beyond source history.",
                why_it_matters="Merged PRs or documentation alone do not prove current production deployment state.",
                who_might_know=anchor_rec["author"],
                evidence_state=EvidenceState.UNKNOWN,
                evidence=[sample_ref],
            )
            knowledge_gaps.append(gap)

            question_suggestions.append(
                ExtractedQuestionSuggestion(
                    question_text=f"Has the change or procedure in '{anchor_rec['title']}' been verified in production?",
                    why_it_matters="Verify production stability before ownership transfer.",
                    suggested_respondent=anchor_rec["author"],
                    related_gap=gap.title,
                    priority="HIGH",
                )
            )

            next_actions.append(
                ExtractedNextAction(
                    title=f"Verify {pack_name} handover readiness",
                    description=f"Review '{anchor_rec['title']}' and confirm environment access and tests.",
                    priority="HIGH",
                    suggested_assignee="Successor",
                    evidence_state=EvidenceState.INFERRED,
                    evidence=[sample_ref],
                )
            )

            transfer_packs.append(
                CandidateTransferPack(
                    name=pack_name,
                    description=f"Responsibility bundle covering {len(recs)} source contributions in {pack_name}.",
                    component_area=pack_name.split()[0],
                    work_items=work_items,
                    decisions=decisions,
                    dependencies=dependencies,
                    risks=risks,
                    operational_notes=operational_notes,
                    knowledge_gaps=knowledge_gaps,
                    next_actions=next_actions,
                    question_suggestions=question_suggestions,
                )
            )

        result = ExtractionResult(transfer_packs=transfer_packs)
        latency = max(1, int((time.time() - start_time) * 1000))
        metadata = {
            "input_tokens": self.count_tokens(user_prompt),
            "output_tokens": 1200,
            "latency_ms": latency,
            "provider_mode": "mock",
            "model_used": self.model_name,
            "fallback_used": False,
            "fallback_reason": None,
        }
        return result, metadata

    def answer_question(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel] = QuestionAnswerResult,
        *,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> tuple[BaseModel, dict[str, Any]]:
        """Generate a grounded draft answer strictly from delimited evidence blocks in user_prompt."""
        start_time = time.time()

        q_match = re.search(r"QUESTION TO ANSWER:\s*(.+)", user_prompt)
        question_text = q_match.group(1).strip() if q_match else ""
        stop = {
            "what", "where", "when", "which", "who", "how", "why", "is", "are", "was", "were",
            "the", "and", "for", "with", "that", "this", "from", "into", "about", "does", "have",
            "can", "will", "should", "current", "project", "service", "handover",
        }
        q_terms = {
            w.lower()
            for w in re.findall(r"[a-zA-Z0-9_-]{3,}", question_text)
            if w.lower() not in stop
        }

        block_pattern = re.compile(
            r"--- EVIDENCE SOURCE[^\n]*\n(.*?)\n--- END EVIDENCE SOURCE ---",
            re.DOTALL,
        )
        matched_sources: list[tuple[int, dict[str, Any]]] = []
        for m in block_pattern.finditer(user_prompt):
            block = m.group(1)
            if "Content:\n" not in block:
                continue
            header_part, body_part = block.split("Content:\n", 1)
            headers: dict[str, str] = {}
            for line in header_part.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip()] = v.strip()
            sid = headers.get("ID", "").strip()
            if not sid:
                continue
            body_clean = body_part.strip()
            title = headers.get("Title", "Source").strip()
            haystack = f"{title} {body_clean}".lower()
            score = sum(1 for t in q_terms if t in haystack)
            if score > 0:
                matched_sources.append((
                    score,
                    {
                        "id": sid,
                        "source_class": headers.get("SourceClass", "SOURCE_RECORD").strip().upper(),
                        "type": headers.get("Type", "RECORD").strip(),
                        "title": title,
                        "state": headers.get("State", "").strip(),
                        "locator": headers.get("Locator", "").strip() or None,
                        "is_stale": headers.get("Stale", "False").strip().lower() == "true",
                        "body": body_clean,
                    },
                ))

        matched_sources.sort(key=lambda tup: (-tup[0], tup[1]["id"]))
        top_matches = [item for _, item in matched_sources[:4]]

        if not top_matches:
            res = response_schema.model_validate({
                "answer_text": (
                    "The answer to this question is not established by the permitted source records "
                    "and claims available for this handover case."
                ),
                "answer_status": "insufficient",
                "evidence_references": [],
                "limitations": (
                    "No ingested GitHub records, documents, or claims in your permitted scope contain "
                    "supporting terms for this question."
                ),
                "conflicts": [],
                "confidence_diagnostic": 0.0,
            })
        else:
            has_conflict = any("CONFLICTING" in (m.get("state") or "").upper() for m in top_matches)
            states_set = {m.get("type", "").upper(): m.get("state", "").lower() for m in top_matches}
            conflict_notes: list[str] = []
            if len(top_matches) >= 2:
                joined_titles = " ".join(m["title"].lower() + " " + m["body"].lower() for m in top_matches)
                if ("microservice" in joined_titles and "monolith" in joined_titles) or (
                    "graphql" in joined_titles and "rest" in joined_titles
                ) or has_conflict:
                    has_conflict = True
                    conflict_notes.append(
                        f"Conflicting positions recorded across '{top_matches[0]['title']}' "
                        f"and '{top_matches[1]['title']}'."
                    )

            has_stale = any(m["is_stale"] for m in top_matches)
            has_merged_pr = any(m["type"].upper() == "PR" and "merged" in (m["state"] or "").lower() for m in top_matches)

            summary_lines = []
            refs: list[dict[str, Any]] = []
            for m in top_matches:
                excerpt, _ = _clean_verbatim_excerpt(m["body"], 160)
                ex_final = excerpt or m["title"]
                summary_lines.append(f"- Based on {m['type']} '{m['title']}': \"{ex_final}\"")
                refs.append({
                    "source_id": m["id"],
                    "source_type": "CLAIM" if m["source_class"] == "CLAIM" else "SOURCE_RECORD",
                    "title": m["title"],
                    "excerpt": ex_final,
                    "locator": m["locator"],
                    "relevance": f"Matched key question terms from {m['type']}",
                    "is_stale": m["is_stale"],
                })

            notes: list[str] = []
            if has_stale:
                notes.append("Note: One or more cited items are marked potentially stale.")
            if has_merged_pr:
                notes.append("Caveat: Merged PRs alone do not confirm live production deployment.")

            if has_conflict:
                header_line = "Conflicting evidence found across available project sources:"
                status_val = "conflicting"
            else:
                header_line = "Draft summary grounded in permitted handover sources:"
                status_val = "answered"

            full_answer = "\n".join([header_line, *summary_lines, *notes]).strip()
            limitation_msg = " ".join(notes) if notes else None

            res = response_schema.model_validate({
                "answer_text": full_answer,
                "answer_status": status_val,
                "evidence_references": refs,
                "limitations": limitation_msg,
                "conflicts": conflict_notes,
                "confidence_diagnostic": round(min(0.95, 0.4 + 0.15 * len(top_matches)), 2),
            })

        latency = max(1, int((time.time() - start_time) * 1000))
        return res, {
            "input_tokens": self.count_tokens(user_prompt),
            "output_tokens": self.count_tokens(res.answer_text),
            "latency_ms": latency,
            "provider_mode": "mock",
            "model_used": "mock-qa-v1",
            "fallback_used": False,
            "fallback_reason": None,
        }
