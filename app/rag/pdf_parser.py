"""PDF text extraction and section splitting (Task 5).

``extract_pages`` turns a PDF file into per-page text (page numbers are
1-based). ``split_sections`` then cuts that page stream into sections by
detecting numbered heading lines; any text before the first heading is
kept as ``"Front Matter"``.

Supported heading schemes (a paper mixes at most arabic + letter):

* arabic — ``1 Introduction``, ``3.2 Results``, ``1. Introduction``,
  ``3.1. Pre-Trained Models``
* roman — ``I. INTRODUCTION``, ``VII. RELATED WORK``
* letter — ``A. Denoising Diffusion Probabilistic Models``

Beyond the line-level shape rules (short, no sentence-final punctuation,
capitalised content words), two context rules keep prose/list lines from
being mistaken for headings:

* **no consecutive headings** — a real section heading is followed by
  body text; author-affiliation blocks are 2-3 *adjacent* lines of the
  same scheme with consecutive numbers ("1 Columbia University / 2 Toyota
  Research Institute / 3 MIT"), so a candidate whose neighbour is also a
  heading-shaped line of the same scheme with an adjacent number is part
  of a list, not a section;
* **strict numbering** — section numbers must start at 1 (A / I) and
  increase by exactly one at each level (letter/subsection counters
  restart after each new top-level section); a regression or a skip marks
  the line as non-heading (stray equation lines like ``"2 T (t), T(t) ="``
  never satisfy the sequence).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

FRONT_MATTER_TITLE = "Front Matter"

# -- line-level shape -------------------------------------------------------

#: hard limits separating headings from prose
_HEADING_MAX_CHARS = 100
_HEADING_MAX_WORDS = 15
#: a line ending in any of these reads as a sentence/list item, not a
#: heading (the comma catches bibliography author lines like "H. Wallach,")
_SENTENCE_FINAL = ".,!?;。！？；"
#: words a heading may keep in lowercase without looking like prose
_HEADING_STOPWORDS = frozenset(
    "a an and as at but by for from in into of on or per the to via with".split()
)
#: "X." inside the content marks a bibliographic initial ("A. Herzog, J. Hsu")
_INITIAL_RE = re.compile(r"^[A-Z]\.?$")
#: content must open at least one word with an ASCII capital — equation and
#: axis-tick lines ("1 2 3 4 5 6 7 8", "1 −α2", "2 ∆pt") have none
_ASCII_UPPER_RE = re.compile(r"[A-Z]")

# scheme patterns; the number/letter token is followed by whitespace
_ARABIC_RE = re.compile(r"^(\d{1,2})(?:\.(\d{1,2}))?(\.)?\s+(.+)$")
_ROMAN_RE = re.compile(r"^([IVXLCDM]{2,7})\.\s+(.+)$")
_LETTER_RE = re.compile(r"^([A-Z])\.\s+(.+)$")
#: canonical roman numerals (for validating the token and computing value)
_ROMAN_CANONICAL_RE = re.compile(
    r"^(?=[IVXLCDM])M*(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)
_ROMAN_DIGITS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_value(token: str) -> int:
    """Value of a canonical roman numeral token (validated by the caller)."""
    total = 0
    prev = 0
    for ch in reversed(token):
        val = _ROMAN_DIGITS[ch]
        total = total - val if val < prev else total + val
        prev = max(prev, val)
    return total


@dataclass
class _Heading:
    """A parsed, shape-valid candidate heading line."""

    scheme: str  # "arabic" | "roman" | "letter"
    token: str  # the number/letter token as written ("1", "3.2", "II", "B")
    title: str  # the full stripped line (becomes Section.title)
    major: int = 0  # arabic: major number
    minor: int = 0  # arabic: minor number (0 = top-level)
    value: int = 0  # roman/letter: 1-based sequence value
    letter_value: int = 0  # ambiguous tokens ("C." is roman 100 AND letter 3)
    ambiguous: bool = False  # single "I."/"V."/"C."-style token: roman or letter


def _parse_heading(stripped: str) -> _Heading | None:
    """Parse a stripped line into a shape-valid heading candidate, or None.

    Shape rules: line ≤ 100 chars and ≤ 15 words, no sentence-final
    punctuation, content words capitalised (a single lowercase content
    word is tolerated for real headings like "A. Simulation Environments
    and datasets"), no bibliographic initials ("J. Hsu") inside the
    content, at least one content word. Superscript-mashed forms
    ("1Columbia University", "1Cheng Chi") never parse: the scheme
    patterns require a separator after the number.
    """
    if len(stripped) > _HEADING_MAX_CHARS:
        return None
    if stripped[-1] in _SENTENCE_FINAL:
        return None
    words = stripped.split()
    if len(words) > _HEADING_MAX_WORDS:
        return None

    for regex, scheme in ((_ARABIC_RE, "arabic"), (_ROMAN_RE, "roman")):
        m = regex.match(stripped)
        if m is None:
            continue
        if scheme == "roman" and not _ROMAN_CANONICAL_RE.match(m.group(1)):
            continue
        content = m.group(m.lastindex) if scheme == "roman" else m.group(4)
        if not _content_is_heading_shaped(content):
            return None
        if scheme == "arabic":
            return _Heading(
                scheme="arabic",
                token=m.group(1) + (f".{m.group(2)}" if m.group(2) else ""),
                title=stripped,
                major=int(m.group(1)),
                minor=int(m.group(2) or 0),
            )
        return _Heading(
            scheme="roman", token=m.group(1), title=stripped,
            value=_roman_value(m.group(1)),
        )

    m = _LETTER_RE.match(stripped)
    if m is not None and _content_is_heading_shaped(m.group(2)):
        token = m.group(1)
        letter_value = ord(token) - ord("A") + 1
        # single "I."/"V."/"C." tokens are both a roman numeral and a
        # letter; the numbering state resolves which one it is
        if token in _ROMAN_DIGITS:
            return _Heading(
                scheme="roman",
                token=token,
                title=stripped,
                value=_roman_value(token),
                letter_value=letter_value,
                ambiguous=True,
            )
        return _Heading(
            scheme="letter",
            token=token,
            title=stripped,
            value=letter_value,
            letter_value=letter_value,
        )
    return None


def _content_is_heading_shaped(content: str) -> bool:
    """True when the words after the number/letter look like a heading title."""
    lowercase = 0
    seen_alpha_cap = False
    for word in content.split():
        if _INITIAL_RE.match(word):
            return False  # "A. Herzog" — a bibliography author, not a heading
        if word.lower() in _HEADING_STOPWORDS:
            continue
        if _ASCII_UPPER_RE.match(word):
            seen_alpha_cap = True
        elif word[0].isalpha() and not word[0].isupper():
            lowercase += 1
            if lowercase > 1:
                # "All experiments use three seeds" is a prose sentence, not
                # a heading (one lowercase word is tolerated: "... and
                # datasets" is a real heading)
                return False
    return seen_alpha_cap


# -- context rules ----------------------------------------------------------


class _HeadingNumbering:
    """Strict per-scheme sequence state (rule b): numbers must start at the
    first value and increase by exactly one; letter and subsection counters
    restart after every new top-level heading. State advances only on
    ACCEPTED headings, so rejected candidates never corrupt the sequence."""

    def __init__(self) -> None:
        self.next_major = 1
        self.current_major = 0
        self.next_minor = 1
        self.next_roman = 1
        self.next_letter = 1  # 1 = "A"

    def accepts(self, h: _Heading) -> bool:
        if h.scheme == "arabic":
            if h.minor == 0:  # top-level: must be the next major exactly
                if h.major != self.next_major:
                    return False
                self.next_major += 1
                self.current_major = h.major
                self.next_minor = 1
                self.next_letter = 1
                return True
            # subsection: same major as the current section, next minor
            if h.major != self.current_major or h.minor != self.next_minor:
                return False
            self.next_minor += 1
            return True
        if h.ambiguous:
            # "I."/"C." — resolve against the active letter run first (paper
            # 5's appendix reaches "I. Additional ..." after "H. ..."), then
            # the roman run, then a fresh letter run
            if self.next_letter > 1 and h.letter_value == self.next_letter:
                self.next_letter += 1
                return True
            if h.value == self.next_roman:
                self.next_roman += 1
                self.next_letter = 1
                return True
            if h.letter_value == self.next_letter:
                self.next_letter += 1
                return True
            return False
        if h.scheme == "roman":
            if h.value != self.next_roman:
                return False
            self.next_roman += 1
            self.next_letter = 1
            return True
        # letter
        if h.value != self.next_letter:
            return False
        self.next_letter += 1
        return True


def _same_list_level(a: _Heading, b: _Heading) -> bool:
    """True when two candidates sit at the same list level (so adjacent
    neighbours with adjacent numbers form a list block)."""
    if a.scheme != b.scheme:
        return False
    if a.scheme == "arabic":
        # both top-level, or both subsections of the same major
        if (a.minor == 0) != (b.minor == 0):
            return False
        return a.major == b.major if a.minor else True
    return True


def _adjacent_value(a: _Heading, b: _Heading) -> bool:
    """True when b's number is a's number ± 1 (a consecutive list run)."""
    if a.scheme == "arabic":
        return abs(a.major - b.major) == 1 if a.minor == 0 \
            else abs(a.minor - b.minor) == 1
    return abs(a.value - b.value) == 1


def _in_list_block(candidate: _Heading, prev: str | None, nxt: str | None) -> bool:
    """Rule a: a real section heading is followed by body text. When the
    neighbouring (non-empty) line is *also* a heading-shaped line of the
    same scheme with an adjacent number, both belong to a numbered list —
    e.g. the author-affiliation block "1 Columbia University /
    2 Toyota Research Institute / 3 MIT" — not to the section structure."""
    for neighbour in (prev, nxt):
        if neighbour is None:
            continue
        other = _parse_heading(neighbour)
        if (
            other is not None
            and _same_list_level(candidate, other)
            and _adjacent_value(candidate, other)
        ):
            return True
    return False


# -- data model & public API ------------------------------------------------


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

    A line becomes a heading when it parses as a numbered/roman/letter
    heading (see :func:`_parse_heading`), is not part of a consecutive
    numbered list block (:func:`_in_list_block`) and fits the strict
    numbering sequence (:class:`_HeadingNumbering`). Heading lines are
    kept as the first line of their section's text; ``Section.page`` is
    the page the heading appears on. Text found before the first heading
    becomes a single ``"Front Matter"`` section (omitted entirely when the
    paper starts with a heading).
    """
    # flatten to non-empty stripped lines with their pages (neighbour
    # checks need the stream, not per-page views)
    lines: list[tuple[int, str]] = []
    for page_text in pages:
        for raw in page_text.text.splitlines():
            stripped = raw.strip()
            if stripped:
                lines.append((page_text.page, stripped))
    if not lines:
        return []

    numbering = _HeadingNumbering()
    headings: dict[int, _Heading] = {}  # line index -> accepted heading
    for i, (_, stripped) in enumerate(lines):
        candidate = _parse_heading(stripped)
        if candidate is None:
            continue
        prev = lines[i - 1][1] if i > 0 else None
        nxt = lines[i + 1][1] if i + 1 < len(lines) else None
        if _in_list_block(candidate, prev, nxt):
            continue
        if numbering.accepts(candidate):
            headings[i] = candidate

    sections: list[Section] = []
    title = FRONT_MATTER_TITLE
    start_page = lines[0][0]
    body: list[str] = []

    def flush() -> None:
        if body:
            sections.append(
                Section(title=title, page=start_page, text="\n".join(body))
            )
            body.clear()

    for i, (page, stripped) in enumerate(lines):
        heading = headings.get(i)
        if heading is not None:
            flush()
            title = heading.title
            start_page = page
        body.append(stripped)
    flush()

    return sections
