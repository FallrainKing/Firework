"""API tests for the paper routes (upload / arXiv / listing)."""

from __future__ import annotations

import pytest
from conftest import GOOD_METADATA_JSON, FakeGateway


def _upload(client, name: str, content: bytes):
    return client.post(
        "/api/papers/upload",
        files={"file": (name, content, "application/pdf")},
    )


def test_upload_pdf_returns_paper_id(api_client, sample_pdf):
    """Upload sample.pdf → 200 {"paper_id": 1}; GET /api/papers lists its title."""
    gw = FakeGateway(fast=GOOD_METADATA_JSON)
    with api_client(gw) as client:
        r = _upload(client, "sample.pdf", sample_pdf.read_bytes())
        assert r.status_code == 200, r.text
        assert r.json() == {"paper_id": 1}

        listing = client.get("/api/papers").json()["papers"]
        assert any(p["title"] == "Sample Research Paper" for p in listing)
        paper = listing[0]
        assert paper["id"] == 1
        assert paper["source"] == "upload"
        assert paper["authors"] == ["Author One", "Author Two"]


def test_upload_duplicate_returns_existing(api_client, sample_pdf):
    """Uploading the same paper twice returns the same id; library stays at 1 row."""
    gw = FakeGateway(fast=GOOD_METADATA_JSON)
    with api_client(gw) as client:
        data = sample_pdf.read_bytes()
        first = _upload(client, "sample.pdf", data)
        second = _upload(client, "sample.pdf", data)
        assert first.status_code == second.status_code == 200
        assert first.json()["paper_id"] == second.json()["paper_id"]

        papers = client.get("/api/papers").json()["papers"]
        assert len(papers) == 1


def test_upload_bad_pdf_returns_400(api_client):
    """A non-PDF upload is a client error with an explicit message, not a 500."""
    with api_client(FakeGateway(fast=GOOD_METADATA_JSON)) as client:
        r = _upload(client, "bad.pdf", b"this is definitely not a pdf")
        assert r.status_code == 400
        assert "pdf" in r.json()["detail"].lower()


def test_arxiv_route_returns_paper_id(api_client, monkeypatch):
    """The arXiv route is wired to ingest_arxiv and returns its paper_id."""

    async def fake_ingest_arxiv(url_or_id, *, db, embedder, store, data_dir):
        assert url_or_id == "https://arxiv.org/abs/2401.00001"
        return 42

    monkeypatch.setattr("app.api.papers.ingest_arxiv", fake_ingest_arxiv)
    with api_client(FakeGateway()) as client:
        r = client.post(
            "/api/papers/arxiv", json={"url": "https://arxiv.org/abs/2401.00001"}
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"paper_id": 42}


def test_arxiv_bad_url_returns_400(api_client):
    """A url without any arXiv id → ValueError from the pipeline → 400."""
    with api_client(FakeGateway()) as client:
        r = client.post("/api/papers/arxiv", json={"url": "not an arxiv link"})
        assert r.status_code == 400
        assert "arxiv" in r.json()["detail"].lower()


def test_upload_store_unavailable_returns_503(api_client):
    """When the vector store could not start, upload answers 503, not 500."""
    with api_client(FakeGateway()) as client:
        client.app.state.store = None
        r = _upload(client, "x.pdf", b"whatever")
        assert r.status_code == 503
