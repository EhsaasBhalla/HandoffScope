"""PDF document parser using PyMuPDF."""

from __future__ import annotations

import logging

import pymupdf as fitz

logger = logging.getLogger("handoffscope.parsers.pdf")


def parse_pdf(file_data: bytes) -> dict:
    """Extract text and metadata from a PDF file.

    Returns dict with keys: text, page_count, sections, quality_warning.
    """
    doc = fitz.open(stream=file_data, filetype="pdf")
    pages = []
    total_text = []
    quality_warning = None

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        pages.append({
            "page": page_num + 1,
            "text": text,
            "char_count": len(text),
        })
        total_text.append(text)

    full_text = "\n\n".join(total_text)

    # Quality check — warn if very little text extracted (likely scanned images)
    avg_chars_per_page = len(full_text) / max(len(doc), 1)
    if avg_chars_per_page < 50:
        quality_warning = (
            "Very little text extracted — document may contain scanned images. "
            "Consider using an OCR-processed version."
        )

    doc.close()

    return {
        "text": full_text,
        "page_count": len(pages),
        "sections": pages,
        "quality_warning": quality_warning,
    }
