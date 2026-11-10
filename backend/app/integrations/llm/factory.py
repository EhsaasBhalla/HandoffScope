"""Factory for instantiating the configured LLM provider.

Phase 6 — AI Extraction & Evidence Engine.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.integrations.llm.base import LLMProvider
from app.integrations.llm.mock_provider import MockLLMProvider

logger = logging.getLogger("handoffscope.llm")


def get_llm_provider() -> LLMProvider:
    """Instantiate and return the configured LLM provider.

    Defaults to MockLLMProvider when no LLM_API_KEY is configured.
    """
    if settings.LLM_API_KEY:
        provider_name = settings.LLM_PROVIDER.lower().strip()
        if provider_name == "openai":
            from app.integrations.llm.openai_provider import OpenAIProvider

            logger.info("Using OpenAI LLM provider (model: %s)", settings.LLM_MODEL_NAME)
            return OpenAIProvider(settings.LLM_API_KEY, settings.LLM_MODEL_NAME)
        else:
            from app.integrations.llm.gemini_provider import GeminiProvider

            logger.info("Using Gemini LLM provider (model: %s)", settings.LLM_MODEL_NAME)
            return GeminiProvider(settings.LLM_API_KEY, settings.LLM_MODEL_NAME)

    logger.info("No LLM_API_KEY set — using grounded MockLLMProvider for offline execution.")
    return MockLLMProvider()
