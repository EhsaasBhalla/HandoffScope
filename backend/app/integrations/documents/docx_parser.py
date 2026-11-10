"""DOCX document parser using python-docx."""

from __future__ import annotations

import io
import logging

from docx import Document as DocxDocument

logger = logging.getLogger("handoffscope.parsers.docx")


def parse_docx(file_data: bytes) -> dict:
    """Extract text and sections from a DOCX file.

    Returns dict with keys: text, page_count, sections, quality_warning.
    """
    doc = DocxDocument(io.BytesIO(file_data))
    sections = []
    current_section = {"heading": "Document Start", "paragraphs": []}

    for para in doc.paragraphs:
        if para.style and para.style.name and para.style.name.startswith("Heading"):
            # Save previous section
            if current_section["paragraphs"]:
                sections.append(current_section)
            current_section = {"heading": para.text, "paragraphs": []}
        elif para.text.strip():
            current_section["paragraphs"].append(para.text)

    # Don't forget the last section
    if current_section["paragraphs"]:
        sections.append(current_section)

    full_text = "\n\n".join(
        f"## {s['heading']}\n" + "\n".join(s["paragraphs"])
        for s in sections
    )

    return {
        "text": full_text,
        "page_count": None,  # DOCX doesn't have reliable page counts
        "sections": sections,
        "section_count": len(sections),
        "quality_warning": None,
    }
