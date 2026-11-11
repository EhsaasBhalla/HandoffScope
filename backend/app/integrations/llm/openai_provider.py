"""OpenAI provider for structured extraction.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import json
import time
from typing import Any, Type

from pydantic import BaseModel

from app.integrations.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):
    """LLM provider backed by OpenAI API."""

    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini"):
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
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai package is not installed. Run `pip install openai`."
            ) from e

        if not self.api_key:
            raise ValueError("OpenAI API key is not configured.")

        client = OpenAI(api_key=self.api_key)
        start_time = time.time()

        completion = client.beta.chat.completions.parse(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        parsed = completion.choices[0].message.parsed
        latency_ms = int((time.time() - start_time) * 1000)

        usage = completion.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return parsed, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "provider_mode": "live",
            "model_used": self.model_name,
            "fallback_used": False,
            "fallback_reason": None,
        }

    def answer_question(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> tuple[BaseModel, dict[str, Any]]:
        return self.extract_structured(
            system_prompt,
            user_prompt,
            response_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
