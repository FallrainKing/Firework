"""PDF text extraction and section splitting (Task 5).

``extract_pages`` turns a PDF file into per-page text (page numbers are
1-based). ``split_sections`` then cuts that page stream into sections by
detecting numbered heading lines with the regex ``^\\d+(\\.\\d+)?\\s+[A-Z]``;
any text before the first numbered heading is kept as ``"Front Matter"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

FRONT_MATTER_TITLE = "Front Matter"

# Numbered heading lines: "1 Introduction", "2 Method", "3.2 Results" …
_HEADING_RE = re.compile(r"^\d+(\.\d+)?\s+[A-Z]")


@dataclass
class PageText:
    """Text of a single PDF page; ``page`` is 1-based."""

    page: int
    text: str


@dataclass
class Section:
    """A contiguous slice of the paper starting at a numbered heading."""

    title: str
    page: int  # page the section's heading appears on (1-based)
    text: str


def extract_pages(pdf_path: str | Path) -> list[PageText]:
    """Extract per-page text from a PDF file, pages numbered from 1."""
    with pymupdf.open(str(pdf_path)) as doc:
        return [PageText(page=i + 1, text=page.get_text("text")) for i, page in enumerate(doc)]


def split_sections(pages: list[PageText]) -> list[Section]:
    """Split a page stream into sections on numbered heading lines.

    A line is a heading when it matches ``^\\d+(\\.\\d+)?\\s+[A-Z]`` after
    stripping. Heading lines are kept as the first line of their section's
    text; ``Section.page`` is the page the heading appears on. Text found
    before the first heading becomes a single ``"Front Matter"`` section
    (omitted entirely when the paper starts with a heading).
    """
    sections: list[Section] = []
    title = FRONT_MATTER_TITLE
    start_page = pages[0].page if pages else 1
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            sections.append(Section(title=title, page=start_page, text=text))

    for page_text in pages:
        for line in page_text.text.splitlines():
            stripped = line.strip()
            if _HEADING_RE.match(stripped):
                flush()
                title = stripped
                start_page = page_text.page
                lines = [stripped]
            else:
                lines.append(line)
    flush()

    return sections
