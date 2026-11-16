"""Qdrant-backed chunk vector store.

Stores one point per document chunk. The payload carries the fields the QA
route (Task 7) needs to cite sources: paper_id, chunk_index, text, page,
section. paper_id filtering happens server-side via a Qdrant Filter, not by
post-filtering results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, VectorParams


class VectorStoreError(Exception):
    """Qdrant connection or request failure, surfaced as our own type."""


@dataclass
class ChunkPoint:
    """A chunk to store: its vector plus the metadata payload."""

    paper_id: int
    chunk_index: int
    text: str
    page: int
    section: str
    vector: list[float]


@dataclass
class SearchHit:
    """A search result: the payload fields back plus the similarity score."""

    paper_id: int
    chunk_index: int
    text: str
    page: int
    section: str
    score: float


# Qdrant accepts unsigned ints or UUIDs as point ids. UUIDv5 derived from
# (paper_id, chunk_index) keeps re-upserting the same chunk idempotent
# (overwrite in place) without inventing a fragile integer packing scheme.
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "research-assistant:chunk")


def _point_id(paper_id: int, chunk_index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{paper_id}:{chunk_index}"))


def _is_unreachable(exc: Exception) -> bool:
    """True if the failure chain contains a transport-level httpx error.

    qdrant-client mostly propagates httpx errors as-is, but may also wrap
    them (e.g. ResponseHandlingException), so the whole ``__cause__`` chain
    is inspected.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.TransportError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _wrap(exc: Exception) -> VectorStoreError:
    """Classify a low-level error: connection issues → unreachable, else request failure.

    Returns the exception (with ``__cause__`` chained) for the caller to raise.
    """
    if _is_unreachable(exc) or "Connection" in type(exc).__name__:
        err = VectorStoreError(f"qdrant unreachable: {exc}")
    else:
        err = VectorStoreError(f"qdrant request failed: {exc}")
    err.__cause__ = exc
    return err


class VectorStore:
    """Thin wrapper around a QdrantClient managing one chunk collection."""

    def __init__(self, client: QdrantClient, collection: str = "chunks"):
        self._client = client
        self._collection = collection

    def ensure_collection(self, dim: int) -> None:
        """Create the collection with `dim`-dim cosine vectors if missing."""
        try:
            if not self._client.collection_exists(self._collection):
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
        except Exception as exc:  # noqa: BLE001 — we re-raise as our own type
            raise _wrap(exc)

    def delete_paper(self, paper_id: int) -> int:
        """Delete every point of one paper; return how many were removed.

        Scrolls all point ids matching the ``paper_id`` payload field (Qdrant
        server-side filter, paged) and removes them in one batch. Deleting an
        unknown paper — or one whose collection doesn't exist yet — is not an
        error and returns 0, so re-ingest callers can call this
        unconditionally before writing the fresh chunk set (stale tail chunks
        from a previous, larger ingest would otherwise survive as orphans).
        """
        from qdrant_client.models import PointIdsList

        paper_filter = Filter(
            must=[FieldCondition(key="paper_id", match=MatchValue(value=paper_id))]
        )
        try:
            if not self._client.collection_exists(self._collection):
                return 0
            ids: list[str] = []
            offset = None
            while True:
                records, offset = self._client.scroll(
                    collection_name=self._collection,
                    scroll_filter=paper_filter,
                    limit=256,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                ids.extend(point.id for point in records)
                if offset is None:
                    break
            if ids:
                self._client.delete(
                    collection_name=self._collection,
                    points_selector=PointIdsList(points=ids),
                )
            return len(ids)
        except Exception as exc:  # noqa: BLE001
            raise _wrap(exc)

    def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        """Insert/overwrite the given chunks (payload: paper_id/chunk_index/text/page/section)."""
        if not points:
            return  # empty batch → no-op, mirroring embed([]) -> []

        from qdrant_client.models import PointStruct

        try:
            self._client.upsert(
                collection_name=self._collection,
                points=[
                    PointStruct(
                        id=_point_id(p.paper_id, p.chunk_index),
                        vector=p.vector,
                        payload={
                            "paper_id": p.paper_id,
                            "chunk_index": p.chunk_index,
                            "text": p.text,
                            "page": p.page,
                            "section": p.section,
                        },
                    )
                    for p in points
                ],
            )
        except Exception as exc:  # noqa: BLE001
            raise _wrap(exc)

    def search(
        self,
        vector: list[float],
        top_k: int = 8,
        paper_id: int | None = None,
    ) -> list[SearchHit]:
        """Return the top_k nearest chunks, optionally restricted to one paper."""
        query_filter = None
        if paper_id is not None:
            # server-side filter (must condition), not post-filtering
            query_filter = Filter(
                must=[FieldCondition(key="paper_id", match=MatchValue(value=paper_id))]
            )
        try:
            response = self._client.query_points(
                collection_name=self._collection,
                query=vector,
                limit=top_k,
                query_filter=query_filter,
            )
        except Exception as exc:  # noqa: BLE001
            raise _wrap(exc)
        return [
            SearchHit(
                paper_id=point.payload["paper_id"],
                chunk_index=point.payload["chunk_index"],
                text=point.payload["text"],
                page=point.payload["page"],
                section=point.payload["section"],
                score=point.score,
            )
            for point in response.points
        ]
