"""Deterministic inline secret & credential redaction filter (Round 3).

Preserves original stored text untouched and produces policy-labeled redacted projections
for shared views, RAG excerpts, exports, and indexed repository snippets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REDACTION_POLICY_VERSION = "r3-secret-filter-v1"

_PLACEHOLDER_MARKERS = (
    "example",
    "placeholder",
    "change-me",
    "changeme",
    "your_",
    "your-",
    "<your",
    "<token>",
    "dummy",
    "sample",
    "xxxx",
    "test-token",
)


@dataclass(frozen=True)
class RedactionResult:
    redacted_text: str
    redactions_applied: int
    categories: list[str]
    policy_version: str = REDACTION_POLICY_VERSION


# Ordered most-specific first; intentionally avoids false positives on UUIDs, normal identifiers, and internal IPs
_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED:PRIVATE_KEY]",
    ),
    (
        "CONNECTION_URI",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|rediss|amqp)://[^:\s/@]+:[^@\s]+@[^\s\"'`]+",
            re.IGNORECASE,
        ),
        "[REDACTED:CONNECTION_URI]",
    ),
    (
        "GITHUB_TOKEN",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
        "[REDACTED:SECRET]",
    ),
    (
        "LINEAR_TOKEN",
        re.compile(r"\blin_api_[A-Za-z0-9]{16,}\b"),
        "[REDACTED:SECRET]",
    ),
    (
        "AWS_KEY",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "[REDACTED:SECRET]",
    ),
    (
        "API_KEY",
        re.compile(
            r"\b(?:AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{20,})\b"
        ),
        "[REDACTED:SECRET]",
    ),
    (
        "JWT_TOKEN",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED:TOKEN]",
    ),
    (
        "CONFIG_SECRET",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:PASSWORD|SECRET_KEY|CLIENT_SECRET|API_KEY|PRIVATE_KEY|ACCESS_TOKEN|AUTH_TOKEN))\s*([:=])\s*([\"']?)([^\s\"'`#,;]{10,})\3"
        ),
        "[REDACTED:SECRET]",
    ),
]


def _is_placeholder(val: str) -> bool:
    low = val.lower()
    if any(p in low for p in _PLACEHOLDER_MARKERS):
        return True
    if len(set(low)) <= 2:
        return True
    return False


def redact_secrets_inline(text: str | None) -> RedactionResult:
    """Return a derived inline-redacted projection without mutating caller inputs."""
    if not text:
        return RedactionResult(redacted_text="", redactions_applied=0, categories=[])

    current = text
    total = 0
    cats: list[str] = []

    for category, pattern, replacement in _RULES:
        if category == "CONFIG_SECRET":
            def _replace_assign(m: re.Match[str]) -> str:
                nonlocal total
                key_name, sep, quote, val = m.group(1), m.group(2), m.group(3), m.group(4)
                if _is_placeholder(val) or val.startswith("[REDACTED"):
                    return m.group(0)
                total += 1
                if category not in cats:
                    cats.append(category)
                return f"{key_name}{sep}{quote}{replacement}{quote}"

            current = pattern.sub(_replace_assign, current)
        else:
            def _replace_tok(m: re.Match[str], cat: str = category, rep: str = replacement) -> str:
                nonlocal total
                matched = m.group(0)
                if _is_placeholder(matched):
                    return matched
                total += 1
                if cat not in cats:
                    cats.append(cat)
                return rep

            current = pattern.sub(_replace_tok, current)

    return RedactionResult(
        redacted_text=current,
        redactions_applied=total,
        categories=cats,
    )
