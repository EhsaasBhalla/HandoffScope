"""Abstract LLM provider interface.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Type

from pydantic import BaseModel


class LLMProvider(ABC):
    """Abstract interface for LLM structured extraction."""

    @abstractmethod
    def extract_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel],
        *,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> tuple[BaseModel, dict[str, Any]]:
        """Extract structured data from LLM matching response_schema.

        Returns:
            tuple of (parsed_pydantic_model, usage_metadata)
            usage_metadata contains: {"input_tokens": int, "output_tokens": int, "latency_ms": int}
        """
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return identifier of the model."""
        ...
