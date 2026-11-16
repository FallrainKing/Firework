"""Sentence-boundary sliding-window chunker (Task 5).

Each section is split into sentences at ``.`` and ``。`` boundaries (both
English and Chinese full stops), then packed into chunks of at most
``max_chars`` characters. Consecutive chunks share a tail/lead window of up
to ``overlap`` characters, while always starting on different sentences.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.pdf_parser import Section

# A sentence is any run of non-delimiter characters ending in "." or "。",
# plus any trailing run without a delimiter (the final sentence).
_SENTENCE_RE = re.compile(r"[^.。]+[.。]?")

_SENTENCE_DELIM_RE = re.compile(r"[.。]")


@dataclass
class Chunk:
    """A retrievable text slice belonging to one section of one paper."""

    section: str
    page: int
    text: str


def split_sentences(text: str) -> list[str]:
    """Split text into sentences at "." and "。", keeping the delimiter.

    Concatenating the returned sentences reproduces the input, so chunk
    texts preserve the original spacing.
    """
    return [s for s in _SENTENCE_RE.findall(text) if s.strip()]


def _overlap_tail(window: list[str], overlap: int) -> list[str]:
    """Longest suffix of ``window`` totalling at most ``overlap`` characters.

    Always returns a *proper* suffix (at least one sentence dropped): if the
    whole window fits inside the overlap budget, the next chunk must still
    start on a new sentence, so the tail is emptied instead.
    """
    tail: list[str] = []
    total = 0
    for sentence in reversed(window):
        if tail and total + len(sentence) > overlap:
            break
        tail.insert(0, sentence)
        total += len(sentence)
    if len(tail) == len(window):
        return []
    return tail


def chunk_sections(
    sections: list[Section], max_chars: int = 1500, overlap: int = 200
) -> list[Chunk]:
    """Chunk each section with a sliding window over sentence boundaries."""
    chunks: list[Chunk] = []
    for section in sections:
        sentences = split_sentences(section.text)
        window: list[str] = []
        window_len = 0
        last_emitted: tuple[str, ...] | None = None

        for sentence in sentences:
            if window and window_len + len(sentence) > max_chars:
                last_emitted = tuple(window)
                chunks.append(
                    Chunk(section=section.title, page=section.page, text="".join(window).strip())
                )
                window = _overlap_tail(window, overlap)
                window_len = sum(len(s) for s in window)
            window.append(sentence)
            window_len += len(sentence)

        # flush the final window (skip a pure duplicate of the last emission)
        if window and tuple(window) != last_emitted:
            chunks.append(
                Chunk(section=section.title, page=section.page, text="".join(window).strip())
            )

    return chunks
