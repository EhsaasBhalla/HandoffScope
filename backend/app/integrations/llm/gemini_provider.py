"""Google Gemini provider for structured extraction using Gemini 1.5/2.0 API.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import json
import time
from typing import Any, Type

from pydantic import BaseModel

from app.integrations.llm.base import LLMProvider


class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini API."""

    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
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
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise RuntimeError(
                "google-generativeai package is not installed. Run `pip install google-generativeai`."
            ) from e

        if not self.api_key:
            raise ValueError("Gemini API key is not configured.")

        genai.configure(api_key=self.api_key)

        start_time = time.time()

        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json",
            },
        )

        response = model.generate_content(user_prompt)
        raw_text = response.text or "{}"

        data = json.loads(raw_text)
        parsed = response_schema.model_validate(data)

        latency_ms = int((time.time() - start_time) * 1000)

        # Estimate tokens if usage metadata is available
        input_tokens = getattr(getattr(response, "usage_metadata", None), "prompt_token_count", 0)
        output_tokens = getattr(getattr(response, "usage_metadata", None), "candidates_token_count", 0)

        return parsed, {
            "input_tokens": input_tokens or len(user_prompt) // 4,
            "output_tokens": output_tokens or len(raw_text) // 4,
            "latency_ms": latency_ms,
        }
