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
      page 2 — intro continuation + "2 Method" + body (including a
               "Model"/"RT-2 55.4 21.1" table-header shape that must NOT
               split), ending with the unnumbered heading "Related Work" +
               body (exercises the unnumbered-heading detection; the
               abstract is kept on the "Abstract—..." line so it does not
               read as a standalone "Abstract" heading)
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
            "Abstract—This is a tiny synthetic paper generated with PyMuPDF for the",
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
            # body lines that merely look like numbered headings (citation
            # year / wrapped-sentence starts): the section splitter must
            # NOT treat these as headings (see test_pdf_parser.py)
            "2023 A Survey of Embodied AI",
            "3 The authors acknowledge...",
            "10 All experiments use three seeds",
            "2 Method",
            "We split pages into sections with a numbered-heading regex.",
            "Then we chunk each section on sentence boundaries.",
            "The method is deliberately simple and deterministic.",
            # a word-list line opening a table (header above a numeric row):
            # must NOT split a section, even though "Model" is in the list
            "Model",
            "RT-2 55.4 21.1",
            "Related Work",
            "Prior work on unnumbered section headings is scarce.",
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


@pytest.fixture(scope="session")
def embedder():
    """The real bge-m3 embedder, loaded once for the whole session."""
    from app.rag.embedder import Embedder

    return Embedder(model_name="BAAI/bge-m3")


@pytest.fixture()
def ingest_stack(tmp_path, embedder):
    """Fresh SQLite db + :memory: Qdrant store + data_dir for one ingest test.

    Returns ``(db, store, data_dir, embedder)``. The db lives inside
    ``tmp_path`` so each test gets a clean papers/chunks_meta state, and the
    store is an in-process Qdrant collection sized to bge-m3's dimension.
    """
    from qdrant_client import QdrantClient

    from app.config import Settings
    from app.db import get_conn
    from app.rag.vector_store import VectorStore

    db = get_conn(Settings(data_dir=tmp_path, qdrant_url="http://localhost:6333"))
    store = VectorStore(QdrantClient(":memory:"), collection="chunks")
    store.ensure_collection(embedder.dimension)
    return db, store, tmp_path, embedder


# ---------------------------------------------------------------------------
# Task 7: API test helpers
# ---------------------------------------------------------------------------

import json as _json

#: strict-JSON metadata reply the fake "fast" tier serves for sample.pdf,
#: so uploads exercise the real LLM-metadata path of the ingest pipeline.
GOOD_METADATA_JSON = _json.dumps(
    {
        "title": "Sample Research Paper",
        "authors": ["Author One", "Author Two"],
        "abstract": "A tiny synthetic paper generated with PyMuPDF.",
    }
)


class FakeGateway:
    """LLM gateway double with per-tier canned replies.

    A tier without a configured reply raises, which (a) makes the upload
    pipeline's metadata extractor fall back to filename-derived metadata —
    what the batch-import tests rely on to get distinct titles per file —
    and (b) makes any unexpected LLM call fail loudly in tests that must
    not talk to a gateway at all.
    """

    def __init__(self, fast: str | None = None, strong: str | None = None):
        self.fast = fast
        self.strong = strong
        self.calls: list[dict] = []

    async def chat(
        self, messages, tier="fast", max_tokens=4096, temperature=None
    ):
        self.calls.append(
            {
                "tier": tier,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        reply = self.fast if tier == "fast" else self.strong
        if reply is None:
            raise RuntimeError(f"fake gateway: no reply configured for tier {tier!r}")
        return {
            "text": reply,
            "thinking": "",
            "provider": "fake",
            "model": "fake",
            "usage": {"input": 0, "output": 0},
        }


@pytest.fixture()
def api_client(tmp_path, monkeypatch, embedder):
    """Factory building a ``TestClient`` whose lifespan wires test doubles.

    ``DATA_DIR`` points at ``tmp_path`` and ``QDRANT_URL`` at ``:memory:``,
    so the real lifespan in ``app.main`` builds a genuine per-test stack
    (sqlite + in-process qdrant). Only the two pieces that must not be real
    are monkeypatched: ``Embedder`` (reuse the session bge-m3 instance
    instead of loading a second copy) and ``LLMGateway`` (the caller's fake).

    The returned client MUST be used as a context manager — otherwise the
    lifespan never runs and background import jobs have no event loop.
    """
    from fastapi.testclient import TestClient

    from app import main

    def _make(gateway) -> TestClient:
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("QDRANT_URL", ":memory:")
        monkeypatch.setattr(
            main, "Embedder", lambda model_name="BAAI/bge-m3": embedder
        )
        monkeypatch.setattr(main, "LLMGateway", lambda settings=None: gateway)
        return TestClient(main.create_app())

    return _make
