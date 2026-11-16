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


def test_single_oversized_sentence_hard_capped():
    # a 3000-char run with no spaces and no sentence delimiters is ONE
    # sentence; it must be hard-split so no chunk exceeds max_chars
    text = "x" * 3000
    chunks = chunk_sections([_long_section(text)])
    assert len(chunks) >= 2
    assert all(len(ch.text) <= 1500 for ch in chunks)
    # hard split, not dropped: the pieces reproduce the input exactly
    assert "".join(ch.text for ch in chunks) == text


def test_oversized_sentence_after_normal_prose_stays_capped():
    # the oversized sentence follows ordinary sentences whose overlap tail
    # would otherwise push the combined chunk past the cap
    text = "A normal sentence opens the section. " + "y" * 2900
    chunks = chunk_sections([_long_section(text)])
    assert len(chunks) >= 2
    assert all(len(ch.text) <= 1500 for ch in chunks)
    assert chunks[0].text.startswith("A normal sentence opens the section.")
    # nothing lost: prose sentence + all pieces are present across chunks
    joined = "".join(ch.text for ch in chunks)
    assert "A normal sentence opens the section." in joined
    assert joined.count("y") == 2900
