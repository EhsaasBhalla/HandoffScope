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

from app.integrations.llm.base import LLMProvider
from app.integrations.llm.mock_provider import MockLLMProvider

logger = logging.getLogger("handoffscope.llm.gemini")

# Order of model candidates to try when Google servers experience demand spikes or deprecations
CANDIDATE_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
]


class GeminiProvider(LLMProvider):
    """Resilient LLM provider backed by Google Gemini REST API with multi-model fallback."""

    def __init__(self, api_key: str, model_name: str = "gemini-3.5-flash"):
        self.api_key = api_key
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
        if not self.api_key:
            logger.warning("Gemini API key is not configured — falling back to MockLLMProvider.")
            return MockLLMProvider().extract_structured(system_prompt, user_prompt, response_schema)

        models_to_try = [self.model_name] + [m for m in CANDIDATE_MODELS if m != self.model_name]
        start_time = time.time()

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            payload = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    "responseMimeType": "application/json",
                },
            }

            try:
                response = httpx.post(url, json=payload, timeout=20.0)
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content_parts = candidates[0].get("content", {}).get("parts", [])
                        if content_parts:
                            raw_text = content_parts[0].get("text", "{}")
                            parsed = response_schema.model_validate(json.loads(raw_text))
                            latency_ms = int((time.time() - start_time) * 1000)

                            usage = data.get("usageMetadata", {})
                            return parsed, {
                                "model_used": model,
                                "input_tokens": usage.get("promptTokenCount", len(user_prompt) // 4),
                                "output_tokens": usage.get("candidatesTokenCount", len(raw_text) // 4),
                                "latency_ms": latency_ms,
                            }
                else:
                    err_msg = response.text[:120]
                    logger.warning("Gemini model %s returned HTTP %s: %s — trying next fallback model...", model, response.status_code, err_msg)
            except Exception as exc:
                logger.warning("Gemini model %s call failed (%s) — trying next fallback model...", model, exc)

        logger.warning("All Gemini cloud models exhausted or unavailable — activating offline MockLLMProvider fallback.")
        return MockLLMProvider().extract_structured(system_prompt, user_prompt, response_schema)
