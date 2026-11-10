"""Plain text / Markdown parser."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("handoffscope.parsers.text")


def parse_text(file_data: bytes, filename: str = "") -> dict:
    """Extract text and sections from plain text or markdown.

    Returns dict with keys: text, page_count, sections, quality_warning.
    """
    text = file_data.decode("utf-8", errors="replace")
    is_markdown = filename.lower().endswith(".md")

    sections = []
    if is_markdown:
        # Split on markdown headings
        parts = re.split(r"(?m)^(#{1,6}\s+.+)$", text)
        current_heading = "Document Start"
        current_body = []

        for part in parts:
            if re.match(r"^#{1,6}\s+", part):
                if current_body:
                    sections.append({
                        "heading": current_heading,
                        "text": "\n".join(current_body).strip(),
                    })
                current_heading = part.strip().lstrip("#").strip()
                current_body = []
            else:
                if part.strip():
                    current_body.append(part)

        if current_body:
            sections.append({
                "heading": current_heading,
                "text": "\n".join(current_body).strip(),
            })
    else:
        # Treat entire file as one section
        sections = [{"heading": "Full Document", "text": text}]

    return {
        "text": text,
        "page_count": None,
        "sections": sections,
        "section_count": len(sections),
        "quality_warning": None,
    }
