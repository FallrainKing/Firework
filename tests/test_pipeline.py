"""Ingest pipeline tests (Task 6).

Real bge-m3 embedder (session fixture, HF mirror per conftest) + a throwaway
SQLite db and an ``:memory:`` Qdrant store per test (``ingest_stack``).
Everything that would hit the network — LLM gateway, arXiv metadata API,
arXiv PDF download — is monkeypatched.
"""

import asyncio
import json
from pathlib import Path

import app.ingest.pipeline as pipeline
from app.ingest.metadata import PaperMeta
from app.ingest.pipeline import ingest_arxiv, ingest_paper
from app.rag.vector_store import ChunkPoint

AUTHORS = ["Author One", "Author Two"]
ABSTRACT = "A tiny synthetic paper generated with PyMuPDF."
CATEGORIES = ["cs.CL"]


def _ingest(sample_pdf, stack, *, source="upload", title="Sample Research Paper"):
    db, store, data_dir, embedder = stack
    return asyncio.run(
        ingest_paper(
            sample_pdf,
            source=source,
            arxiv_id=None,
            title=title,
            authors=AUTHORS,
            abstract=ABSTRACT,
            categories=CATEGORIES,
            db=db,
            embedder=embedder,
            store=store,
            data_dir=data_dir,
        )
    )


def _row(db, paper_id):
    return db.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()


def _chunk_count(db, paper_id):
    return db.execute(
        "SELECT COUNT(*) FROM chunks_meta WHERE paper_id=?", (paper_id,)
    ).fetchone()[0]


def test_ingest_pdf_creates_paper_and_chunks(sample_pdf, ingest_stack):
    db, store, data_dir, embedder = ingest_stack
    paper_id = _ingest(sample_pdf, ingest_stack)

    # papers: exactly one row with the given metadata
    assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
    row = _row(db, paper_id)
    assert row is not None
    assert row["title"] == "Sample Research Paper"
    assert row["source"] == "upload"
    assert row["arxiv_id"] is None
    assert json.loads(row["authors"]) == AUTHORS
    assert json.loads(row["categories"]) == CATEGORIES

    # PDF copied to data_dir/papers/{id}.pdf and recorded on the row
    stored_pdf = data_dir / "papers" / f"{paper_id}.pdf"
    assert stored_pdf.exists()
    assert stored_pdf.read_bytes() == Path(sample_pdf).read_bytes()
    assert row["pdf_path"] == str(stored_pdf)

    # chunks_meta: rows written for every chunk
    n_chunks = _chunk_count(db, paper_id)
    assert n_chunks > 0

    # qdrant: ingested chunks retrievable, filtered to this paper
    hits = store.search(
        embedder.embed(["sections are split with a numbered-heading regex"])[0],
        top_k=4,
        paper_id=paper_id,
    )
    assert hits, "ingested chunks must be retrievable from Qdrant"
    assert all(hit.paper_id == paper_id for hit in hits)
    assert all(hit.chunk_index < n_chunks for hit in hits)


def test_ingest_arxiv_end_to_end(sample_pdf, ingest_stack, monkeypatch):
    db, store, data_dir, embedder = ingest_stack

    async def fake_meta(url_or_id):
        return PaperMeta(
            arxiv_id="2401.00001",
            title="Attention Is All You Need for Sample Papers",
            authors=AUTHORS,
            abstract="This is the abstract text.",
            categories=["cs.CL", "cs.LG"],
            published="2024-01-02T18:00:00Z",
        )

    async def fake_download(arxiv_id):
        assert arxiv_id == "2401.00001", "version suffix must be stripped"
        return Path(sample_pdf).read_bytes()

    monkeypatch.setattr(pipeline, "fetch_arxiv_metadata", fake_meta)
    monkeypatch.setattr(pipeline, "download_arxiv_pdf", fake_download)

    paper_id = asyncio.run(
        ingest_arxiv(
            "https://arxiv.org/abs/2401.00001v2",
            db=db,
            embedder=embedder,
            store=store,
            data_dir=data_dir,
        )
    )

    row = _row(db, paper_id)
    assert row is not None
    assert row["arxiv_id"] == "2401.00001"
    assert row["source"] == "arxiv"
    assert row["title"] == "Attention Is All You Need for Sample Papers"
    assert json.loads(row["categories"]) == ["cs.CL", "cs.LG"]
    assert _chunk_count(db, paper_id) > 0
    assert (data_dir / "papers" / f"{paper_id}.pdf").exists()


def test_reingest_replaces_old_chunks(sample_pdf, ingest_stack):
    # Task 4 review carry-over: re-ingesting a paper whose new chunk set is
    # smaller than the old one must not leave orphan points behind (a
    # paper_id-filtered search would otherwise still return the stale tail).
    db, store, data_dir, embedder = ingest_stack
    paper_id = _ingest(sample_pdf, ingest_stack)
    n_chunks = _chunk_count(db, paper_id)

    # simulate the stale tail: an extra point beyond the current chunk count
    orphan_vec = embedder.embed(["stale orphan chunk text"])[0]
    store.upsert_chunks(
        [
            ChunkPoint(
                paper_id=paper_id,
                chunk_index=n_chunks + 5,
                text="stale orphan chunk text",
                page=9,
                section="Old",
                vector=orphan_vec,
            )
        ]
    )

    paper_id_again = _ingest(sample_pdf, ingest_stack)

    assert paper_id_again == paper_id, "re-ingest reuses the existing paper row"
    assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
    assert _chunk_count(db, paper_id) == n_chunks

    hits = store.search(orphan_vec, top_k=64, paper_id=paper_id)
    assert hits, "fresh chunks must be searchable"
    assert all(hit.chunk_index < n_chunks for hit in hits), (
        "orphan tail points from the previous ingest must be gone"
    )
