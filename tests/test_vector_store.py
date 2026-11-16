"""Tests for the Qdrant-backed vector store.

Uses ``QdrantClient(":memory:")`` (local mode) — no real Qdrant service is
needed. Only the unreachable-endpoint test touches the network (and fails to
connect, by design).
"""

import pytest
from qdrant_client import QdrantClient

from app.rag.vector_store import ChunkPoint, SearchHit, VectorStore, VectorStoreError


def make_point(paper_id, chunk_index, text, vector):
    return ChunkPoint(
        paper_id=paper_id,
        chunk_index=chunk_index,
        text=text,
        page=chunk_index + 1,
        section="body",
        vector=vector,
    )


def fake_vector(seed, dim=8):
    return [float((seed * (i + 1)) % 7) / 7.0 for i in range(dim)]


def test_filter_by_paper():
    store = VectorStore(QdrantClient(":memory:"), collection="chunks")
    store.ensure_collection(8)
    store.upsert_chunks(
        [
            make_point(10, 0, "paper A chunk 0", fake_vector(1)),
            make_point(10, 1, "paper A chunk 1", fake_vector(2)),
            make_point(20, 0, "paper B chunk 0", fake_vector(3)),
            make_point(20, 1, "paper B chunk 1", fake_vector(4)),
        ]
    )

    hits = store.search(fake_vector(1), top_k=8, paper_id=10)

    assert hits, "filtered search must return results"
    assert all(hit.paper_id == 10 for hit in hits)
    # all 2 chunks of paper 10 are candidates, none from paper 20
    assert sorted(hit.chunk_index for hit in hits) == [0, 1]
    # payload round-trips into SearchHit fields
    hit = hits[0]
    assert isinstance(hit, SearchHit)
    assert hit.text == f"paper A chunk {hit.chunk_index}"
    assert hit.page == hit.chunk_index + 1
    assert hit.section == "body"
    assert isinstance(hit.score, float)


def test_delete_paper():
    # Task 4 review carry-over: re-ingesting a paper needs to drop all of its
    # old points (including stale tail chunks) before writing the new set.
    store = VectorStore(QdrantClient(":memory:"), collection="chunks")
    store.ensure_collection(8)
    store.upsert_chunks(
        [
            make_point(10, 0, "paper A chunk 0", fake_vector(1)),
            make_point(10, 1, "paper A chunk 1", fake_vector(2)),
            make_point(20, 0, "paper B chunk 0", fake_vector(3)),
            make_point(20, 1, "paper B chunk 1", fake_vector(4)),
        ]
    )

    deleted = store.delete_paper(10)

    assert deleted == 2, "delete_paper reports the number of removed points"
    assert store.search(fake_vector(1), top_k=8, paper_id=10) == []
    # other papers untouched
    hits = store.search(fake_vector(3), top_k=8, paper_id=20)
    assert sorted(hit.chunk_index for hit in hits) == [0, 1]

    # deleting an unknown (or already-deleted) paper is fine and returns 0
    assert store.delete_paper(10) == 0
    assert store.delete_paper(999) == 0


def test_unreachable_qdrant_raises_clean_error():
    # URL points at a port nothing listens on → the store must translate the
    # low-level httpx/connect error into our own exception, not leak it.
    # check_compatibility=False skips qdrant-client's version probe, whose
    # failure would only add an unrelated UserWarning to the output.
    client = QdrantClient(url="http://localhost:59999", timeout=2.0, check_compatibility=False)
    store = VectorStore(client, collection="chunks")

    with pytest.raises(VectorStoreError) as excinfo:
        store.ensure_collection(8)
    assert "unreachable" in str(excinfo.value).lower()

    with pytest.raises(VectorStoreError):
        store.search([0.0] * 8, top_k=1)
