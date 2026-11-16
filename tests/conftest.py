"""Shared test configuration.

Ruling R4: HuggingFace is unreachable from this network, so all model
downloads must go through the hf-mirror.com mirror. This must be set BEFORE
anything imports ``sentence_transformers`` (the endpoint is read at import
time by the huggingface_hub machinery), hence it lives at the very top of
conftest.py, before any test module can run.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _build_sample_pdf(path: Path) -> None:
    """Generate the minimal two-page sample paper used by the parser tests.

    Layout (page numbers are 1-based):
      page 1 — title/authors/abstract (front matter) + "1 Introduction" + body
      page 2 — intro continuation + "2 Method" + body
    """
    import pymupdf

    doc = pymupdf.open()
    y = 72  # first text baseline

    def write(page, lines):
        nonlocal y
        for line in lines:
            page.insert_text((72, y), line, fontname="helv", fontsize=11)
            y += 16

    page1 = doc.new_page()
    y = 72
    write(
        page1,
        [
            "Sample Research Paper",
            "Author One and Author Two",
            "Abstract",
            "This is a tiny synthetic paper generated with PyMuPDF for the",
            "parser and chunker test suite. It exercises numbered section",
            "headings, multi-page sections, and plain English sentences.",
            "1 Introduction",
            "Research assistants need to read papers quickly.",
            "Parsing a PDF into pages and sections is the first step.",
            "This introduction continues onto the next page so that a",
            "section can span multiple pages.",
        ],
    )

    page2 = doc.new_page()
    y = 72
    write(
        page2,
        [
            "The introduction keeps flowing here before the next heading.",
            "2 Method",
            "We split pages into sections with a numbered-heading regex.",
            "Then we chunk each section on sentence boundaries.",
            "The method is deliberately simple and deterministic.",
        ],
    )

    doc.save(str(path))
    doc.close()


@pytest.fixture(scope="session")
def sample_pdf() -> Path:
    """Path to tests/fixtures/sample.pdf, generating it on first use."""
    path = FIXTURES_DIR / "sample.pdf"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _build_sample_pdf(path)
    return path
