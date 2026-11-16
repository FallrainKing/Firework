"""Tests for the sentence-boundary sliding-window chunker (Task 5)."""

from app.rag.chunker import Chunk, chunk_sections
from app.rag.pdf_parser import Section


def _long_section(text: str, title: str = "1 Introduction", page: int = 1) -> Section:
    return Section(title=title, page=page, text=text)


def test_chunk_overlap():
    # contract: exact Chunk dataclass shape
    c = Chunk(section="2 Method", page=2, text="hello")
    assert (c.section, c.page, c.text) == ("2 Method", 2, "hello")

    # ~3700 chars: many sentences, forces multiple chunks at max_chars=500
    sentences = [f"Fact number {i} about the method is stated here. " for i in range(80)]
    long_text = "".join(sentences)
    assert len(long_text) > 1500

    chunks = chunk_sections([_long_section(long_text)], max_chars=500, overlap=100)
    assert len(chunks) >= 3

    # every chunk knows its section and page
    assert all(ch.section == "1 Introduction" and ch.page == 1 for ch in chunks)

    # each chunk respects max_chars (no runaway windows)
    assert all(len(ch.text) <= 500 for ch in chunks)

    firsts = [ch.text.split(". ")[0] for ch in chunks]
    # adjacent chunks overlap (next starts with a sentence that appeared in
    # prev) but never start with the same sentence
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.text.split(". ")[0] in prev.text
    assert len(set(firsts)) == len(firsts)

    # short sections stay a single chunk, text preserved verbatim
    short = chunk_sections(
        [Section(title="2 Method", page=2, text="One short section. Two sentences only.")],
        max_chars=500,
        overlap=100,
    )
    assert len(short) == 1
    assert short[0].text == "One short section. Two sentences only."

    # Chinese sentence boundaries (。) are respected too
    zh = chunk_sections(
        [Section(title="3 实验", page=3, text="这是第一句。这是第二句。这是第三句。")],
        max_chars=500,
        overlap=100,
    )
    assert len(zh) == 1
    assert zh[0].text == "这是第一句。这是第二句。这是第三句。"

    # default parameters: max_chars=1500, overlap=200
    mid = "Sentence around the default limit. " * 80  # ~2700 chars
    default_chunks = chunk_sections([_long_section(mid)])
    assert len(default_chunks) >= 2
    assert all(len(ch.text) <= 1500 for ch in default_chunks)
