"""Tests for PDF page extraction and section splitting (Task 5)."""

from app.rag.pdf_parser import extract_pages, split_sections


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
