"""Shared helpers for parsed document section chunking and locator mapping."""

from __future__ import annotations

import re
from typing import Any


def build_document_section_chunks(
    sections: list[dict[str, Any]] | None,
    full_text: str | None = None,
    *,
    max_chunk_chars: int = 1800,
) -> list[dict[str, Any]]:
    """Normalise parser sections into locator-tagged chunks without mutating full document text."""
    normalized: list[dict[str, Any]] = []

    if sections:
        for idx, sec in enumerate(sections, start=1):
            if not isinstance(sec, dict):
                continue
            if "page" in sec:
                text = (sec.get("text") or "").strip()
                locator = f"Page {sec['page']}"
                heading = locator
            else:
                heading = (sec.get("heading") or f"Section {idx}").strip()
                if "paragraphs" in sec:
                    text = "\n".join(p for p in (sec.get("paragraphs") or []) if p).strip()
                else:
                    text = (sec.get("text") or "").strip()
                locator = f"Section: {heading}" if heading else f"Section {idx}"

            if text:
                normalized.append({
                    "index": len(normalized) + 1,
                    "locator": locator[:200],
                    "heading": heading[:200],
                    "text": text[:max_chunk_chars],
                    "char_count": len(text),
                })

    if not normalized and full_text and full_text.strip():
        parts = re.split(r"(?m)^(#{1,6}\s+.+)$", full_text)
        heading = "Document Overview"
        buf: list[str] = []
        for part in parts:
            if re.match(r"^#{1,6}\s+", part):
                joined = "\n".join(buf).strip()
                if joined:
                    normalized.append({
                        "index": len(normalized) + 1,
                        "locator": f"Section: {heading}"[:200],
                        "heading": heading[:200],
                        "text": joined[:max_chunk_chars],
                        "char_count": len(joined),
                    })
                heading = part.strip().lstrip("#").strip() or "Section"
                buf = []
            elif part.strip():
                buf.append(part.strip())

        tail = "\n".join(buf).strip()
        if tail:
            normalized.append({
                "index": len(normalized) + 1,
                "locator": f"Section: {heading}"[:200],
                "heading": heading[:200],
                "text": tail[:max_chunk_chars],
                "char_count": len(tail),
            })

    return normalized
