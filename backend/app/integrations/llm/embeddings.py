"""Embedding provider abstraction for Conversational RAG (Round 3).

Supports Google Gemini Embedding REST API (`gemini-embedding-001` with configurable
Matryoshka dimensionality) and an honest `lexical_only` fallback when live embedding
keys or endpoints are unavailable (never generates fake random semantic vectors).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("handoffscope.rag.embeddings")

GEMINI_EMBED_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class EmbeddingResult:
    """Typed return container for document/query embeddings."""

    def __init__(
        self,
        *,
        vectors: list[list[float]] | None,
        model_id: str,
        dimension: int,
        provider_mode: str,  # "live_gemini" | "lexical_only"
        error: str | None = None,
    ):
        self.vectors = vectors
        self.model_id = model_id
        self.dimension = dimension
        self.provider_mode = provider_mode
        self.error = error


class GeminiEmbeddingProvider:
    """Configurable REST client for Google Gemini `gemini-embedding-001`."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = "gemini-embedding-001",
        dimension: int = 768,
        timeout_seconds: float = 20.0,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds

    def embed_texts(self, texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[],
                model_id=self.model_name,
                dimension=self.dimension,
                provider_mode="live_gemini",
            )

        url = f"{GEMINI_EMBED_BASE}/{self.model_name}:batchEmbedContents?key={self.api_key}"
        vectors: list[list[float]] = []
        batch_size = 32

        try:
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                requests_payload = [
                    {
                        "model": f"models/{self.model_name}",
                        "content": {"parts": [{"text": (t or " ")[:8000]}]},
                        "taskType": task_type,
                        "outputDimensionality": self.dimension,
                    }
                    for t in batch
                ]
                last_exc: Exception | None = None
                for attempt in range(2):
                    try:
                        resp = httpx.post(
                            url,
                            json={"requests": requests_payload},
                            timeout=self.timeout_seconds,
                        )
                        if resp.status_code in (429, 502, 503, 504) and attempt == 0:
                            time.sleep(0.5)
                            continue
                        resp.raise_for_status()
                        data = resp.json()
                        embs = data.get("embeddings") or []
                        if len(embs) != len(batch):
                            raise ValueError("Mismatched embedding count from Gemini API")
                        for item in embs:
                            vals = [float(v) for v in (item.get("values") or [])]
                            if not vals:
                                raise ValueError("Empty embedding vector received")
                            vectors.append(vals)
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                if last_exc is not None:
                    raise last_exc

            actual_dim = len(vectors[0]) if vectors else self.dimension
            return EmbeddingResult(
                vectors=vectors,
                model_id=self.model_name,
                dimension=actual_dim,
                provider_mode="live_gemini",
            )
        except Exception as exc:
            logger.warning("Gemini embeddings unavailable (%s) — degrading honestly to lexical_only", exc)
            return EmbeddingResult(
                vectors=None,
                model_id="lexical",
                dimension=0,
                provider_mode="lexical_only",
                error=str(exc),
            )


def embed_documents_safe(texts: list[str]) -> EmbeddingResult:
    """Embed document chunks if live provider & API key are enabled, else return lexical_only."""
    if (
        settings.RAG_EMBEDDING_PROVIDER.lower() != "gemini"
        or settings.LLM_PROVIDER.lower() == "mock"
        or not (settings.LLM_API_KEY or "").strip()
    ):
        return EmbeddingResult(
            vectors=None,
            model_id="lexical",
            dimension=0,
            provider_mode="lexical_only",
        )
    provider = GeminiEmbeddingProvider(
        api_key=settings.LLM_API_KEY.strip(),
        model_name=settings.RAG_EMBEDDING_MODEL,
        dimension=settings.RAG_EMBEDDING_DIMENSION,
    )
    return provider.embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")


def embed_query_safe(query_text: str) -> EmbeddingResult:
    """Embed a single user query after permission checks, or degrade cleanly to lexical_only."""
    if (
        settings.RAG_EMBEDDING_PROVIDER.lower() != "gemini"
        or settings.LLM_PROVIDER.lower() == "mock"
        or not (settings.LLM_API_KEY or "").strip()
    ):
        return EmbeddingResult(
            vectors=None,
            model_id="lexical",
            dimension=0,
            provider_mode="lexical_only",
        )
    provider = GeminiEmbeddingProvider(
        api_key=settings.LLM_API_KEY.strip(),
        model_name=settings.RAG_EMBEDDING_MODEL,
        dimension=settings.RAG_EMBEDDING_DIMENSION,
    )
    return provider.embed_texts([query_text], task_type="RETRIEVAL_QUERY")
