"""PDF text extraction and section splitting (Task 5).

``extract_pages`` turns a PDF file into per-page text (page numbers are
1-based). ``split_sections`` then cuts that page stream into sections by
detecting numbered heading lines; any text before the first numbered
heading is kept as ``"Front Matter"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

FRONT_MATTER_TITLE = "Front Matter"

# Numbered heading lines: "1 Introduction", "2 Method", "3.2 Results" …
# The leading number is capped at two digits (one optional dotted
# subsection): four-digit years ("2023 A Survey of Embodied AI") are body
# prose quoting a citation year, never a section number.
_HEADING_RE = re.compile(r"^\d{1,2}(\.\d{1,2})?\s+[A-Z]")

# Shape constraints separating real headings from prose lines that merely
# begin with a number + capital letter (empirically mis-split samples:
# "3 The authors acknowledge...", "10 All experiments use three seeds").
_HEADING_MAX_CHARS = 100
_HEADING_MAX_WORDS = 15
#: sentence-final punctuation disqualifies a heading line
_SENTENCE_FINAL = ".!?;。！？；"
#: words a heading may keep in lowercase without looking like prose
_HEADING_STOPWORDS = frozenset(
    "a an and as at but by for from in into of on or per the to via with".split()
)


def _is_heading(line: str) -> bool:
    """True when a stripped line looks like a numbered section heading.

    Beyond the ``\\d{1,2}(\\.\\d{1,2})?\\s+[A-Z]`` prefix, the line must be
    heading-shaped: short (≤ ``_HEADING_MAX_CHARS`` chars / ≤
    ``_HEADING_MAX_WORDS`` words), free of sentence-final punctuation, and
    with its content words capitalised — so prose like
    ``"10 All experiments use three seeds"`` (lowercase content words) or
    ``"3 The authors acknowledge..."`` (sentence punctuation) is rejected
    while real headings ("2 Method", "3.2 Related Work") still match.
    """
    stripped = line.strip()
    if not _HEADING_RE.match(stripped):
        return False
    if len(stripped) > _HEADING_MAX_CHARS:
        return False
    if stripped[-1] in _SENTENCE_FINAL:
        return False
    words = stripped.split()
    if len(words) > _HEADING_MAX_WORDS:
        return False
    # content words (everything after the section number, minus stopwords)
    # must start uppercase — lowercase words like "experiments use three
    # seeds" mark the line as prose
    content = [w for w in words[1:] if w.lower() not in _HEADING_STOPWORDS]
    if not content:
        return False
    return all(not w[0].isalpha() or w[0].isupper() for w in content)


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

    A line is a heading when it matches ``\\d{1,2}(\\.\\d{1,2})?\\s+[A-Z]``
    *and* is heading-shaped (see :func:`_is_heading`). Heading lines are
    kept as the first line of their section's text; ``Section.page`` is the
    page the heading appears on. Text found before the first heading
    becomes a single ``"Front Matter"`` section (omitted entirely when the
    paper starts with a heading).
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
            if _is_heading(stripped):
                flush()
                title = stripped
                start_page = page_text.page
                lines = [stripped]
            else:
                lines.append(line)
    flush()

    return sections
