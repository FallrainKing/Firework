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


def _split_oversized(sentences: list[str], max_chars: int) -> list[str]:
    """Hard-split any single sentence longer than ``max_chars``.

    Pathological input (e.g. a 3000-character run with no spaces and no
    sentence delimiters) is a single sentence for the window logic; without
    a hard cut it would be emitted as one chunk above the cap. The cut
    carries no delimiters, so nothing is lost — joining the pieces
    reproduces the sentence.
    """
    out: list[str] = []
    for sentence in sentences:
        while len(sentence) > max_chars:
            out.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if sentence.strip():
            out.append(sentence)
    return out


def chunk_sections(
    sections: list[Section], max_chars: int = 1500, overlap: int = 200
) -> list[Chunk]:
    """Chunk each section with a sliding window over sentence boundaries.

    No chunk ever exceeds ``max_chars``: oversized sentences are hard-split
    (see :func:`_split_oversized`), and when even a single sentence plus the
    overlap tail would overshoot, the tail is dropped (it duplicates the
    previous chunk anyway).
    """
    chunks: list[Chunk] = []
    for section in sections:
        sentences = _split_oversized(split_sentences(section.text), max_chars)
        window: list[str] = []
        window_len = 0
        # positional bookkeeping (indexes into `sentences`): the final
        # window is emitted only if it contains at least one sentence the
        # last emission did not already cover — value comparison would
        # wrongly drop repeated identical pieces (e.g. hard-split halves)
        window_start = 0
        last_emitted_end = -1  # exclusive index of the last in-loop emission

        for idx, sentence in enumerate(sentences):
            if window and window_len + len(sentence) > max_chars:
                chunks.append(
                    Chunk(section=section.title, page=section.page, text="".join(window).strip())
                )
                last_emitted_end = idx
                window = _overlap_tail(window, overlap)
                window_start = idx - len(window)
                window_len = sum(len(s) for s in window)
            if window and window_len + len(sentence) > max_chars:
                # a single sentence + the overlap tail still overshoots the
                # cap — sacrifice the tail (it duplicates the last emission)
                window = []
                window_len = 0
                window_start = idx
            window.append(sentence)
            window_len += len(sentence)

        # flush the final window (skip a pure duplicate of the last emission)
        if window and window_start + len(window) > last_emitted_end:
            chunks.append(
                Chunk(section=section.title, page=section.page, text="".join(window).strip())
            )

    return chunks
