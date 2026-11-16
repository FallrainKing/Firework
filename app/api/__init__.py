"""HTTP API package (Task 7): papers, QA and folder-import routers.

The shared helpers here map ingest-pipeline exceptions onto HTTP errors
(the pipeline deliberately raises raw exceptions — Task 6 review concern)
and answer 503 when the embedder/vector store failed to start.
"""

from __future__ import annotations

from importlib import import_module as _import_module

import httpx
import pymupdf
from fastapi import HTTPException, Request

from ..llm.gateway import LLMHTTPStatusError
from ..rag.vector_store import VectorStoreError

#: exceptions the ingest stack raises for *known-bad* inputs or environments;
#: anything else is unexpected and becomes a logged 500.
KNOWN_INGEST_ERRORS: tuple[type[BaseException], ...] = (
    ValueError,  # covers json.JSONDecodeError + arXiv-id extraction failures
    pymupdf.FileDataError,  # bad/scanned PDF bytes (RuntimeError subclass)
    pymupdf.EmptyFileError,
    VectorStoreError,
    LLMHTTPStatusError,  # provider rejected the request (HTTP 4xx)
    httpx.HTTPError,  # upstream (arXiv) request failures
)


def ingest_http_error(exc: Exception) -> HTTPException:
    """Map a raised pipeline exception to the closest HTTP error.

    A qdrant connection failure is a server-side availability problem (503);
    everything else in KNOWN_INGEST_ERRORS is a bad request (400).
    """
    if isinstance(exc, VectorStoreError) and str(exc).startswith("qdrant unreachable"):
        return HTTPException(
            status_code=503, detail=f"vector store unavailable: {exc}"
        )
    return HTTPException(status_code=400, detail=f"ingest failed: {exc}")


def require_rag_stack(request: Request) -> None:
    """Raise 503 unless the embedder and vector store both started.

    The lifespan deliberately keeps the app running when the RAG stack
    cannot initialize (e.g. qdrant unreachable); routes that need it say so
    with a clear message instead of crashing with an opaque error.
    """
    state = request.app.state
    if getattr(state, "embedder", None) is None or getattr(state, "store", None) is None:
        raise HTTPException(
            status_code=503,
            detail="embedding/vector store unavailable (qdrant unreachable at startup?)",
        )


from . import papers, qa  # noqa: E402  (helpers above must exist first)

# ``app.api.import`` cannot be loaded with a normal import statement —
# ``import`` is a Python keyword — so it is imported dynamically here and
# re-exported as ``imports`` for app.main to wire up.
imports = _import_module("app.api.import")

__all__ = [
    "KNOWN_INGEST_ERRORS",
    "ingest_http_error",
    "require_rag_stack",
    "imports",
    "papers",
    "qa",
]
