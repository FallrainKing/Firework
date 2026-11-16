"""Tests for PDF page extraction and section splitting (Task 5)."""

from app.rag.pdf_parser import PageText, extract_pages, split_sections


def test_extract_pages(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert len(pages) == 2
    # page numbers are 1-based
    assert [p.page for p in pages] == [1, 2]
    assert "Introduction" in pages[0].text
    assert "Method" in pages[1].text
    # all pages carry non-empty text
    assert all(isinstance(p.text, str) and p.text.strip() for p in pages)


def test_split_sections(sample_pdf):
    pages = extract_pages(sample_pdf)
    sections = split_sections(pages)

    titles = [s.title for s in sections]
    assert "1 Introduction" in titles
    assert "2 Method" in titles
    # text before the first numbered heading becomes "Front Matter"
    assert titles == ["Front Matter", "1 Introduction", "2 Method"]

    front, intro, method = sections
    # Front Matter holds the title/abstract, not the "1 Introduction" heading
    assert "Sample Research Paper" in front.text
    assert "Abstract" in front.text
    assert "Introduction" not in front.text

    # a section keeps its own heading line and starts on its heading's page
    assert intro.text.lstrip().startswith("1 Introduction")
    assert intro.page == 1
    # the introduction spans page 2 as well (multi-page section)
    assert "next page" in intro.text
    assert "keeps flowing here" in intro.text

    assert method.text.lstrip().startswith("2 Method")
    assert method.page == 2
    # Method section does not swallow the introduction's spillover text
    assert "keeps flowing here" not in method.text


def test_prose_lines_are_not_headings():
    """Body lines that merely *start* like a numbered heading must not split.

    Empirically mis-split samples (each once matched ``^\\d+\\s+[A-Z]``):
    a citation year, a wrapped sentence, and a mid-sentence continuation.
    """
    prose = [
        "2023 A Survey of Embodied AI",  # 4-digit year, not a section number
        "3 The authors acknowledge...",  # ends with sentence punctuation
        "10 All experiments use three seeds",  # prose: lowercase content words
        "We also verified longer wrapped sentences keep flowing here and the",
        "parser must never tear them out of their surrounding paragraph.",
    ]
    pages = [PageText(page=1, text="\n".join(["1 Introduction", *prose]))]
    sections = split_sections(pages)

    # exactly one section: the real heading, with all prose lines inside it
    assert [s.title for s in sections] == ["1 Introduction"]
    for line in prose:
        assert line in sections[0].text


def test_heading_shape_still_matches_real_headings():
    """Real numbered (sub)section headings survive the added constraints."""
    lines = [
        "1 Introduction",
        "Body text.",
        "3.2 Experimental Results and Discussion",
        "More body text.",
        "4 Conclusion and Future Work",
        "End.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "1 Introduction",
        "3.2 Experimental Results and Discussion",
        "4 Conclusion and Future Work",
    ]


def test_sample_pdf_prose_lines_stay_in_body(sample_pdf):
    """The mis-split-prone body lines baked into the fixture stay in the body."""
    sections = split_sections(extract_pages(sample_pdf))
    assert [s.title for s in sections] == ["Front Matter", "1 Introduction", "2 Method"]
    body = "\n".join(s.text for s in sections)
    assert "2023 A Survey of Embodied AI" in body
    assert "3 The authors acknowledge..." in body
    assert "10 All experiments use three seeds" in body
