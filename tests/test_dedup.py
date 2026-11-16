"""Dedup tests (Task 6): cross-source title dedup with no false positives.

Uses the real bge-m3 embedder (vector fallback path) and the ``:memory:``
Qdrant store; the paper is ingested via the real pipeline first.
"""

import asyncio

from app.ingest.dedup import find_duplicate
from app.ingest.pipeline import ingest_paper

TITLE = "Diffusion Policy: Learning Visuomotor Robot Policies"


def _ingest_diffusion(sample_pdf, ingest_stack):
    db, store, data_dir, embedder = ingest_stack
    return asyncio.run(
        ingest_paper(
            sample_pdf,
            source="upload",
            arxiv_id=None,
            title=TITLE,
            authors=["Author One"],
            abstract="Robots learning policies via diffusion.",
            categories=["cs.RO"],
            db=db,
            embedder=embedder,
            store=store,
            data_dir=data_dir,
        )
    )


def test_dedup_same_title_different_source(sample_pdf, ingest_stack):
    db, store, data_dir, embedder = ingest_stack
    paper_id = _ingest_diffusion(sample_pdf, ingest_stack)

    # a differently-spaced title (as an arXiv feed might deliver it) still
    # resolves to the already-ingested upload
    hit = asyncio.run(
        find_duplicate(
            "Diffusion  Policy: Learning Visuomotor Robot Policies",
            embedder=embedder,
            store=store,
            db=db,
        )
    )

    assert hit is not None, "exact-title dedup must hit despite spacing"
    assert hit["id"] == paper_id
    assert hit["title"] == TITLE
    assert hit["source"] == "upload"


def test_no_false_positive(sample_pdf, ingest_stack):
    db, store, data_dir, embedder = ingest_stack
    _ingest_diffusion(sample_pdf, ingest_stack)

    # unrelated title: no exact match, and the vector fallback scores below
    # the 0.92 threshold → None, never a wrong paper
    hit = asyncio.run(
        find_duplicate(
            "Reinforcement Learning for Navigation",
            embedder=embedder,
            store=store,
            db=db,
        )
    )
    assert hit is None
