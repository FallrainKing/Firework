"""Tests for arXiv metadata fetching (Task 5).

All HTTP traffic is faked by monkeypatching the ``httpx`` name inside
``app.ingest.metadata`` — no real requests are ever made. Async code is
driven with ``asyncio.run`` (no pytest-asyncio dependency).
"""

import asyncio
from types import SimpleNamespace

import pytest

import app.ingest.metadata as metadata
from app.ingest.metadata import PaperMeta, extract_arxiv_id, fetch_arxiv_metadata

# Minimal Atom feed in the shape returned by
# http://export.arxiv.org/api/query?id_list=2401.00001
SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>ArXiv Query: search_query=&#123;all&#125;</title>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <published>2024-01-02T18:00:00Z</published>
    <title>Attention Is All You Need for Sample Papers</title>
    <summary>
      This is the abstract text.
      It spans multiple lines with   extra whitespace.
    </summary>
    <author><name>Author One</name></author>
    <author><name>Author Two</name></author>
    <arxiv:primary_category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL"/>
    <category term="cs.LG"/>
  </entry>
</feed>"""

EMPTY_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>"""


class _FakeResponse:
    status_code = 200

    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeAsyncClient:
    requested_urls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        type(self).requested_urls.append(url)
        return _FakeResponse(SAMPLE_ATOM)


def test_fetch_arxiv_metadata(monkeypatch):
    monkeypatch.setattr(metadata, "httpx", SimpleNamespace(AsyncClient=_FakeAsyncClient))
    _FakeAsyncClient.requested_urls.clear()

    # a full abs URL is accepted; the version suffix is stripped
    meta = asyncio.run(fetch_arxiv_metadata("https://arxiv.org/abs/2401.00001v2"))

    assert isinstance(meta, PaperMeta)
    assert meta.arxiv_id == "2401.00001"
    # the bare id (no version) is what goes on the wire
    assert len(_FakeAsyncClient.requested_urls) == 1
    assert "http://export.arxiv.org/api/query?id_list=2401.00001" in _FakeAsyncClient.requested_urls[0]

    assert meta.title == "Attention Is All You Need for Sample Papers"
    assert meta.authors == ["Author One", "Author Two"]
    # abstract is whitespace-normalized
    assert meta.abstract == "This is the abstract text. It spans multiple lines with extra whitespace."
    assert meta.categories == ["cs.CL", "cs.LG"]
    assert meta.published == "2024-01-02T18:00:00Z"

    # every documented input form reduces to the same bare id
    for form in (
        "2401.00001",
        "2401.00001v2",
        "arXiv:2401.00001v2",
        "http://arxiv.org/abs/2401.00001",
        "https://arxiv.org/abs/2401.00001v2",
        "https://arxiv.org/abs/2401.00001v2?fmt=txt",  # query string stripped
    ):
        assert extract_arxiv_id(form) == "2401.00001", form

    # old-style ids survive too (the archive prefix must not be cut by "/")
    assert extract_arxiv_id("hep-th/9901001v2") == "hep-th/9901001"
    assert extract_arxiv_id("https://arxiv.org/abs/cs.CL/0309001") == "cs.CL/0309001"

    # garbage input is rejected, not silently mangled
    with pytest.raises(ValueError):
        extract_arxiv_id("not-an-arxiv-id")

    # a feed without an <entry> is an explicit error
    with pytest.raises(ValueError):
        metadata.parse_arxiv_atom(EMPTY_ATOM, "2401.00001")


def test_extract_arxiv_id_case_and_pdf_urls():
    # F1: the id body keeps its own casing — the subject-class part of
    # old-style ids is canonically uppercase (cs.CL), it must not be lowercased
    assert extract_arxiv_id("cs.CL/0309001v2") == "cs.CL/0309001"
    assert extract_arxiv_id("arXiv:hep-th/9901001v2") == "hep-th/9901001"

    # F2: pdf links (the natural input for a PDF ingest pipeline) are accepted
    assert extract_arxiv_id("https://arxiv.org/pdf/2401.00001v2") == "2401.00001"
    assert extract_arxiv_id("http://arxiv.org/pdf/hep-th/9901001v2") == "hep-th/9901001"
    assert extract_arxiv_id("https://arxiv.org/pdf/2401.00001v2?fmt=pdf") == "2401.00001"
