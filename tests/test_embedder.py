"""Tests for the bge-m3 embedder.

These tests use the real ``BAAI/bge-m3`` model (~2.3GB). The first run
downloads it through the HF mirror configured in conftest.py; afterwards it
is served from the local HF cache.
"""

from app.rag.embedder import Embedder


def test_embedder_dimension():
    emb = Embedder(model_name="BAAI/bge-m3")
    assert emb.dimension == 1024

    vectors = emb.embed(["hello world", "你好世界"])
    assert len(vectors) == 2
    for vec in vectors:
        assert isinstance(vec, list)
        assert len(vec) == 1024
        assert all(isinstance(x, float) for x in vec)
    # two different texts must map to different vectors
    assert vectors[0] != vectors[1]

    # contract: empty input → empty output, no model call
    assert emb.embed([]) == []


def test_cross_language_search():
    from qdrant_client import QdrantClient

    from app.rag.vector_store import ChunkPoint, VectorStore

    emb = Embedder(model_name="BAAI/bge-m3")
    store = VectorStore(QdrantClient(":memory:"), collection="chunks")
    store.ensure_collection(emb.dimension)

    texts = [
        "Diffusion Policy learns robot control as denoising",
        "VLA 视觉语言动作模型",
    ]
    vectors = emb.embed(texts)
    store.upsert_chunks(
        [
            ChunkPoint(
                paper_id=1,
                chunk_index=i,
                text=texts[i],
                page=1,
                section="abstract",
                vector=vectors[i],
            )
            for i in range(2)
        ]
    )

    query_vec = emb.embed(["什么是扩散策略"])[0]
    hits = store.search(query_vec, top_k=2)

    assert len(hits) == 2
    top = hits[0]
    assert top.text == texts[0]  # Chinese query lands on the English chunk
    assert top.score >= hits[1].score
