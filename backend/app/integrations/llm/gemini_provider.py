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

_ORIGINAL_HTTPX_POST = httpx.post

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
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Reuse keep-alive connection pool to eliminate TCP/TLS handshake latency on repeated API calls."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.timeout_seconds,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=30.0),
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

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
        # Strip leading/trailing markdown code fences even if preceded by prose
        fence_idx = raw.find("```")
        if fence_idx != -1 and (raw.lstrip().startswith("```") or raw.find("{") > fence_idx):
            after_fence = raw[fence_idx:].splitlines()
            if after_fence and after_fence[0].startswith("```"):
                after_fence = after_fence[1:]
            for end_i, line in enumerate(after_fence):
                if line.strip() == "```":
                    after_fence = after_fence[:end_i]
                    break
            raw = "\n".join(after_fence).strip()
        first_brace = raw.find("{")
        if first_brace > 0:
            raw = raw[first_brace:]
        return raw or "{}"

    @staticmethod
    def _sanitize_json_string_controls(text: str) -> str:
        """Escape literal control characters inside JSON string literals while keeping structure intact."""
        out: list[str] = []
        in_str = False
        escaped = False
        for ch in text:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\" and in_str:
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_str = not in_str
                out.append(ch)
                continue
            if in_str and ord(ch) < 32:
                if ch == "\n":
                    out.append("\\n")
                elif ch == "\r":
                    out.append("\\r")
                elif ch == "\t":
                    out.append("\\t")
                else:
                    out.append(f"\\u{ord(ch):04x}")
                continue
            out.append(ch)
        return "".join(out)

    @staticmethod
    def _close_json_containers(text: str, *, close_open_string: bool = True) -> str | None:
        """Close any dangling string literal and open JSON brackets/braces at EOF."""
        stripped = text.strip()
        if not stripped.startswith("{"):
            return None

        stack: list[str] = []
        in_str = False
        escaped = False
        for ch in stripped:
            if escaped:
                escaped = False
                continue
            if ch == "\\" and in_str:
                escaped = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch in ("{", "["):
                    stack.append(ch)
                elif ch == "}" and stack and stack[-1] == "{":
                    stack.pop()
                elif ch == "]" and stack and stack[-1] == "[":
                    stack.pop()

        candidate = stripped
        if in_str:
            if not close_open_string:
                return None
            if escaped:
                candidate = candidate[:-1]
            candidate += '"'

        # Remove trailing dangling comma before closing brackets
        candidate = candidate.rstrip()
        while candidate.endswith(","):
            candidate = candidate[:-1].rstrip()

        # Drop trailing incomplete key before comma/close (e.g. `, "rationale":`)
        while candidate.endswith(":"):
            last_comma = candidate.rfind(",")
            last_open = max(candidate.rfind("{"), candidate.rfind("["))
            cut = max(last_comma, last_open)
            if cut <= 0:
                break
            if candidate[cut] == ",":
                candidate = candidate[:cut].rstrip()
            else:
                candidate = candidate[: cut + 1]

        closing = {"{": "}", "[": "]"}
        for opener in reversed(stack):
            candidate += closing[opener]
        return candidate

    @classmethod
    def _parse_and_validate(cls, raw_text: str, response_schema: Type[BaseModel]) -> BaseModel:
        """Parse Gemini text cleanly, handling control newlines and truncated JSON tails."""
        clean = cls._sanitize_json_string_controls(raw_text)
        candidates: list[str] = [raw_text, clean]

        # Build trimmed variant up to last '}' in case of trailing prose
        last_brace = clean.rfind("}")
        if clean.startswith("{") and last_brace > 0:
            candidates.append(clean[: last_brace + 1])

        # Build truncation recovery candidates ONLY when text starts with '{'
        if clean.lstrip().startswith("{"):
            direct_closed = cls._close_json_containers(clean, close_open_string=True)
            if direct_closed:
                candidates.append(direct_closed)
            # Also try rolling back to each of the last few complete '}' boundaries (drops incomplete tail object)
            pos = len(clean)
            for _ in range(4):
                prev_obj_end = clean.rfind("}", 0, pos)
                if prev_obj_end <= 0:
                    break
                rolled = cls._close_json_containers(clean[: prev_obj_end + 1], close_open_string=False)
                if rolled:
                    candidates.append(rolled)
                pos = prev_obj_end

        last_exc: Exception | None = None
        seen: set[str] = set()
        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            try:
                data = json.loads(cand, strict=False)
                return response_schema.model_validate(data)
            except Exception as exc:
                last_exc = exc

        assert last_exc is not None
        raise last_exc

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
            cur_max_tokens = max_tokens
            retried_truncation = False

            for attempt in range(max(self.max_retries, 0) + 1):
                payload = {
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": cur_max_tokens,
                        "responseMimeType": "application/json",
                    },
                }
                finish_reason = None
                usage: dict[str, Any] = {}
                try:
                    if httpx.post is not _ORIGINAL_HTTPX_POST:
                        response = httpx.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
                    else:
                        response = self._get_client().post(url, headers=headers, json=payload)
                    if response.status_code == 200:
                        data = response.json()
                        usage = data.get("usageMetadata", {}) or {}
                        candidates = data.get("candidates", [])
                        if candidates:
                            finish_reason = candidates[0].get("finishReason")
                            content_parts = candidates[0].get("content", {}).get("parts", [])
                            if content_parts:
                                raw_text = self._extract_json_text(content_parts)
                                parsed = self._parse_and_validate(raw_text, response_schema)
                                if (
                                    non_empty_pack_check
                                    and hasattr(parsed, "transfer_packs")
                                    and not parsed.transfer_packs
                                    and "--- SOURCE RECORD" in user_prompt
                                ):
                                    raise ValueError("Gemini returned empty transfer_packs for non-empty context")
                                latency_ms = int((time.time() - start_time) * 1000)
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
                    token_note = (
                        f" finishReason={finish_reason} thoughts={usage.get('thoughtsTokenCount')} out={usage.get('candidatesTokenCount')}"
                        if finish_reason or usage
                        else ""
                    )
                    last_error_reason = (
                        f"Gemini model {model} validation error: {type(exc).__name__}: {str(exc)[:100]}{token_note}"
                    )
                    if finish_reason == "MAX_TOKENS" and not retried_truncation and attempt < self.max_retries:
                        retried_truncation = True
                        cur_max_tokens = min(max(cur_max_tokens * 2, 16384), 32768)
                        logger.warning(
                            "%s — retrying once with expanded maxOutputTokens=%d",
                            last_error_reason,
                            cur_max_tokens,
                        )
                        continue
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
        max_tokens: int = 16384,
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
        max_tokens: int = 8192,
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
