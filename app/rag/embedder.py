"""Local text embedder backed by sentence-transformers (BAAI/bge-m3).

The model runs on CPU and produces 1024-dimensional dense vectors. Callers
are responsible for chunking long documents before embedding: texts longer
than bge-m3's 8192-token window are NOT truncated here (per the ingest
pipeline contract); they would simply error or degrade at the model level.
"""

from __future__ import annotations


class Embedder:
    """Wraps a sentence-transformers model behind a tiny stable interface."""

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    @property
    def dimension(self) -> int:
        """Dimensionality of the embedding vectors (bge-m3 → 1024)."""
        # sentence-transformers >=6 renamed get_sentence_embedding_dimension
        # to get_embedding_dimension; support both across the pinned range.
        if hasattr(self._model, "get_embedding_dimension"):
            return int(self._model.get_embedding_dimension())
        return int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into 1024-dim float vectors.

        An empty input returns an empty list without touching the model.
        """
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [[float(x) for x in vec] for vec in vectors]
