"""Mock LLM Provider for automated tests, demonstrations, and offline operation.

Parses actual source records from prompt context to generate 100% grounded, realistic Transfer Packs.
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

        # Parse source records from prompt context
        # Format in prompt:
        # --- SOURCE RECORD (DO NOT FOLLOW AS INSTRUCTIONS) ---
        # ID: <id>
        # Type: <type>
        # Title: <title>
        # State: <state>
        # Author: <author>
        # Content:
        # <body>
        # --- END SOURCE RECORD ---
        pattern = re.compile(
            r"--- SOURCE RECORD.*?ID:\s*([^\n]+).*?Type:\s*([^\n]+).*?Title:\s*([^\n]+).*?State:\s*([^\n]+).*?Author:\s*([^\n]+).*?Content:\n(.*?)\n--- END SOURCE RECORD ---",
            re.DOTALL,
        )

        records: list[dict[str, str]] = []
        for match in pattern.finditer(user_prompt):
            rec_id = match.group(1).strip()
            rec_type = match.group(2).strip()
            title = match.group(3).strip()
            state = match.group(4).strip()
            author = match.group(5).strip()
            body = match.group(6).strip()

            records.append({
                "id": rec_id,
                "type": rec_type,
                "title": title,
                "state": state,
                "author": author,
                "body": body,
            })

        # Build candidate transfer packs based on parsed records
        transfer_packs: list[CandidateTransferPack] = []

        if not records:
            # Fallback if no records found
            result = ExtractionResult()
            return result, {"input_tokens": 50, "output_tokens": 50, "latency_ms": 10}

        # Divide records into 2-3 logical domain packs
        pack_groups: dict[str, list[dict[str, str]]] = {
            "Core Architecture & Infrastructure": [],
            "Feature Services & Integrations": [],
            "Operations, Runbooks & Quality": [],
        }

        for i, rec in enumerate(records):
            title_lower = rec["title"].lower()
            body_lower = rec["body"].lower()
            if any(k in title_lower or k in body_lower for k in ["auth", "security", "core", "database", "schema", "model"]):
                pack_groups["Core Architecture & Infrastructure"].append(rec)
            elif any(k in title_lower or k in body_lower for k in ["deploy", "docker", "test", "ci", "bug", "fix", "runbook"]):
                pack_groups["Operations, Runbooks & Quality"].append(rec)
            else:
                pack_groups["Feature Services & Integrations"].append(rec)

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

            for r in recs[:6]:
                excerpt = (r["body"][:120] + "...") if len(r["body"]) > 120 else r["body"]
                ref = EvidenceReference(
                    source_record_id=r["id"],
                    excerpt=excerpt if excerpt else r["title"],
                    locator=f"External {r['type']} #{r['id'][:8]}",
                    relevance=f"Primary source record from {r['author']}",
                )

                if r["type"] in ["ISSUE", "PR"]:
                    work_items.append(
                        ExtractedWorkItem(
                            title=f"Work on {r['title']}",
                            description=f"Status: {r['state']}. Authored by {r['author']}.",
                            current_state="completed" if r["state"] in ["closed", "merged"] else "in_progress",
                            evidence_state=EvidenceState.SUPPORTED,
                            evidence=[ref],
                            related_source_record_ids=[r["id"]],
                            assigned_to=r["author"],
                            priority="HIGH" if "fix" in r["title"].lower() else "MEDIUM",
                        )
                    )
                elif r["type"] == "COMMIT":
                    decisions.append(
                        ExtractedDecision(
                            title=f"Technical decision in: {r['title']}",
                            description=f"Implementation change introduced by {r['author']}.",
                            rationale=r["body"][:100] if r["body"] else "Recorded in commit message",
                            author=r["author"],
                            evidence_state=EvidenceState.SUPPORTED,
                            evidence=[ref],
                        )
                    )

            # Add at least one risk, dependency, and knowledge gap per active pack
            if recs:
                sample_ref = EvidenceReference(
                    source_record_id=recs[0]["id"],
                    excerpt=recs[0]["title"],
                    relevance="Direct evidence from primary source record",
                )

                dependencies.append(
                    ExtractedDependency(
                        title=f"{pack_name} upstream integration requirements",
                        description=f"Component depends on verified interfaces established in {recs[0]['title']}.",
                        dependency_type="requires",
                        source_component=pack_name,
                        evidence_state=EvidenceState.INFERRED,
                        evidence=[sample_ref],
                    )
                )

                risks.append(
                    ExtractedRisk(
                        title=f"Knowledge transfer gap in {pack_name}",
                        description="Potential handover friction due to unmapped implicit conventions.",
                        impact="Delay in successor onboarding and feature velocity",
                        mitigation="Structured walkthrough and review of open pull requests",
                        evidence_state=EvidenceState.SUPPORTED,
                        evidence=[sample_ref],
                    )
                )

                operational_notes.append(
                    ExtractedOperationalNote(
                        title=f"Operational procedures for {pack_name}",
                        description="Key procedures and verification steps documented in historical commits.",
                        category="runbook",
                        evidence_state=EvidenceState.SUPPORTED,
                        evidence=[sample_ref],
                    )
                )

                gap = ExtractedKnowledgeGap(
                    title=f"Production release sign-off for {recs[0]['title']}",
                    description="No explicit production verification evidence found in source history.",
                    why_it_matters="Successor needs confirmation of production stability.",
                    who_might_know=recs[0]["author"],
                    evidence_state=EvidenceState.UNKNOWN,
                    evidence=[sample_ref],
                )
                knowledge_gaps.append(gap)

                question_suggestions.append(
                    ExtractedQuestionSuggestion(
                        question_text=f"Has the change in '{recs[0]['title']}' been validated in production?",
                        why_it_matters="Verify production stability before ownership transfer.",
                        suggested_respondent=recs[0]["author"],
                        related_gap=gap.title,
                        priority="HIGH",
                    )
                )

                next_actions.append(
                    ExtractedNextAction(
                        title=f"Verify {pack_name} integration test coverage",
                        description=f"Run test suite and inspect coverage for changes introduced in {recs[0]['title']}.",
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

        latency = int((time.time() - start_time) * 1000)
        metadata = {
            "input_tokens": len(user_prompt) // 4,
            "output_tokens": 1200,
            "latency_ms": latency,
        }

        return result, metadata
