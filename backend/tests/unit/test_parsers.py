"""Unit tests for document parsers (Text, Markdown, DOCX)."""

from app.integrations.documents.text_parser import parse_text


def test_plain_text_parsing():
    content = b"This is a sample document for testing plain text parsing."
    res = parse_text(content, filename="test.txt")
    assert "sample document" in res["text"]
    assert res["section_count"] == 1
    assert res["quality_warning"] is None


def test_markdown_parsing_with_headings():
    content = b"""# Introduction
This is the intro section.

## Architecture
Here is the system architecture.

### Storage
Postgres and Redis are used.
"""
    res = parse_text(content, filename="spec.md")
    assert res["section_count"] == 3
    headings = [s["heading"] for s in res["sections"]]
    assert "Introduction" in headings
    assert "Architecture" in headings
    assert "Storage" in headings
