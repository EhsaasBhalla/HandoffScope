"""Google Gemini provider for structured extraction using Gemini 3.5/3.6 API with resilient fallbacks.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Type

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.mock_provider import MockLLMProvider
from app.integrations.llm.schemas.qa import QuestionAnswerResult

logger = logging.getLogger("handoffscope.llm.gemini")

TRANSIENT_HTTP_CODES = {429, 502, 503, 504}

# Order of model candidates to try when Google servers experience demand spikes or deprecations
CANDIDATE_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
]


class GeminiProvider(LLMProvider):
    """Resilient LLM provider backed by Google Gemini REST API with bounded retries and explicit fallback."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3.5-flash",
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds or settings.LLM_REQUEST_TIMEOUT_SECONDS
        self.max_retries = settings.LLM_MAX_RETRIES if max_retries is None else max_retries

    def get_model_name(self) -> str:
        return self.model_name

    @staticmethod
    def _safe_retry_delay(resp: httpx.Response | None, attempt: int) -> float:
        base_delay = min(1.0 * (2 ** attempt), 3.0)
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(max(float(retry_after), 0.1), 3.0)
                except ValueError:
                    pass
        return base_delay

    @staticmethod
    def _extract_json_text(content_parts: list[dict]) -> str:
        """Extract non-thought text content and strip markdown fences if present."""
        text_chunks = [
            p.get("text", "")
            for p in content_parts
            if isinstance(p, dict) and not p.get("thought") and p.get("text")
        ]
        if not text_chunks and content_parts:
            text_chunks = [p.get("text", "") for p in content_parts if isinstance(p, dict) and p.get("text")]
        raw = "\n".join(text_chunks).strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        return raw or "{}"

    def _invoke_with_fallback(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel],
        temperature: float,
        max_tokens: int,
        mock_callable,
        mock_fallback_model: str,
        non_empty_pack_check: bool = False,
    ) -> tuple[BaseModel, dict[str, Any]]:
        if not self.api_key:
            logger.warning("Gemini API key is not configured — using explicit mock_fallback.")
            res, meta = mock_callable(system_prompt, user_prompt, response_schema, temperature=temperature, max_tokens=max_tokens)
            meta["provider_mode"] = "mock_fallback"
            meta["model_used"] = mock_fallback_model
            meta["fallback_used"] = True
            meta["fallback_reason"] = "LLM_API_KEY not configured"
            return res, meta

        models_to_try = [self.model_name] + [m for m in CANDIDATE_MODELS if m != self.model_name]
        start_time = time.time()
        last_error_reason = "Unknown Gemini provider error"

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            headers = {
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    "responseMimeType": "application/json",
                },
            }

            for attempt in range(max(self.max_retries, 0) + 1):
                try:
                    response = httpx.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            content_parts = candidates[0].get("content", {}).get("parts", [])
                            if content_parts:
                                raw_text = self._extract_json_text(content_parts)
                                parsed = response_schema.model_validate(json.loads(raw_text))
                                if (
                                    non_empty_pack_check
                                    and hasattr(parsed, "transfer_packs")
                                    and not parsed.transfer_packs
                                    and "--- SOURCE RECORD" in user_prompt
                                ):
                                    raise ValueError("Gemini returned empty transfer_packs for non-empty context")
                                latency_ms = int((time.time() - start_time) * 1000)
                                usage = data.get("usageMetadata", {})
                                return parsed, {
                                    "model_used": model,
                                    "provider_mode": "live",
                                    "fallback_used": False,
                                    "fallback_reason": None,
                                    "input_tokens": usage.get("promptTokenCount", self.count_tokens(user_prompt)),
                                    "output_tokens": usage.get("candidatesTokenCount", self.count_tokens(raw_text)),
                                    "latency_ms": latency_ms,
                                }
                        last_error_reason = f"Gemini model {model} returned no valid candidates"
                        break

                    if response.status_code in TRANSIENT_HTTP_CODES:
                        last_error_reason = f"Gemini model {model} HTTP {response.status_code}"
                        logger.warning("%s (attempt %d/%d)", last_error_reason, attempt + 1, self.max_retries + 1)
                        if attempt < self.max_retries:
                            time.sleep(self._safe_retry_delay(response, attempt))
                            continue
                        break

                    err_snippet = (response.text or "")[:120].replace("\n", " ")
                    last_error_reason = f"Gemini model {model} HTTP {response.status_code}: {err_snippet}"
                    logger.warning("%s — moving to next candidate model", last_error_reason)
                    break

                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error_reason = f"Gemini model {model} transport error: {type(exc).__name__}"
                    logger.warning("%s (attempt %d/%d)", last_error_reason, attempt + 1, self.max_retries + 1)
                    if attempt < self.max_retries:
                        time.sleep(self._safe_retry_delay(None, attempt))
                        continue
                    break
                except Exception as exc:
                    last_error_reason = f"Gemini model {model} validation error: {type(exc).__name__}: {str(exc)[:100]}"
                    logger.warning("%s — skipping retry on schema/parse failure", last_error_reason)
                    break

        logger.error("All Gemini cloud models unavailable (%s) — falling back to explicit mock_fallback.", last_error_reason)
        res, meta = mock_callable(system_prompt, user_prompt, response_schema, temperature=temperature, max_tokens=max_tokens)
        meta["provider_mode"] = "mock_fallback"
        meta["model_used"] = mock_fallback_model
        meta["fallback_used"] = True
        meta["fallback_reason"] = last_error_reason[:200]
        return res, meta

    def extract_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel],
        *,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> tuple[BaseModel, dict[str, Any]]:
        return self._invoke_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
            mock_callable=MockLLMProvider().extract_structured,
            mock_fallback_model="mock-extraction-v1",
            non_empty_pack_check=True,
        )

    def answer_question(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel] = QuestionAnswerResult,
        *,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> tuple[BaseModel, dict[str, Any]]:
        return self._invoke_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
            mock_callable=MockLLMProvider().answer_question,
            mock_fallback_model="mock-qa-v1",
            non_empty_pack_check=False,
        )
