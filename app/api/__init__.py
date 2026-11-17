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

from ..ingest.pipeline import PdfTooLargeError
from ..llm.gateway import LLMExhaustedError, LLMHTTPStatusError
from ..rag.vector_store import VectorStoreError
from ..study.reader import InterpretationError

#: exceptions the ingest stack raises for *known-bad* inputs or environments;
#: anything else is unexpected and becomes a logged 500.
KNOWN_INGEST_ERRORS: tuple[type[BaseException], ...] = (
    ValueError,  # covers json.JSONDecodeError + arXiv-id extraction failures
    pymupdf.FileDataError,  # bad/scanned PDF bytes (RuntimeError subclass)
    pymupdf.EmptyFileError,
    PdfTooLargeError,  # arXiv download over the 50MB cap → 400, not 500
    VectorStoreError,
    LLMHTTPStatusError,  # provider rejected the request (HTTP 4xx)
    httpx.HTTPError,  # upstream (arXiv) request failures
)

#: exceptions the study (deep-read / compare) stack raises deliberately.
#: Note ValueError is in both tuples on purpose: study routes catch
#: KNOWN_STUDY_ERRORS first so a compare failure reads as a compare problem.
KNOWN_STUDY_ERRORS: tuple[type[BaseException], ...] = (
    InterpretationError,  # the read pipeline could not complete → 502
    LLMExhaustedError,  # every provider failed/returned empty text → 502
    ValueError,  # compare input problems (missing paper) → 400
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


def study_http_error(exc: Exception) -> HTTPException:
    """Map a study-stack exception to its HTTP error.

    InterpretationError means the reading pipeline ran but could not finish
    (no indexed content, six-dim JSON refusing to parse) and
    LLMExhaustedError means every provider failed or returned empty text —
    both upstream/LLM problems, so 502 (the LLMExhaustedError detail carries
    the per-provider ``attempts`` attribution). A bare ValueError is a bad
    request (400): today that is compare_papers finding a paper id that does
    not exist.
    """
    if isinstance(exc, LLMExhaustedError):
        return HTTPException(
            status_code=502,
            detail=f"llm exhausted: {exc} (attempts: {exc.attempts})",
        )
    if isinstance(exc, InterpretationError):
        return HTTPException(
            status_code=502, detail=f"interpretation failed: {exc}"
        )
    return HTTPException(status_code=400, detail=f"invalid request: {exc}")


def require_rag_stack(request: Request) -> None:
    """Raise 503 unless the embedder and vector store both started.

    Startup retries and aborts when the RAG stack cannot initialize (see
    ``app.main``), so this is a belt-and-braces guard: if the stack ever
    ends up missing at runtime, routes that need it say so with a clear
    message instead of crashing with an opaque error.
    """
    state = request.app.state
    if getattr(state, "embedder", None) is None or getattr(state, "store", None) is None:
        raise HTTPException(
            status_code=503,
            detail="embedding/vector store unavailable (qdrant unreachable at startup?)",
        )


from . import notes, papers, qa, study  # noqa: E402  (helpers above must exist first)

# ``app.api.import`` cannot be loaded with a normal import statement —
# ``import`` is a Python keyword — so it is imported dynamically here and
# re-exported as ``imports`` for app.main to wire up.
imports = _import_module("app.api.import")

__all__ = [
    "KNOWN_INGEST_ERRORS",
    "KNOWN_STUDY_ERRORS",
    "ingest_http_error",
    "study_http_error",
    "require_rag_stack",
    "imports",
    "notes",
    "papers",
    "qa",
    "study",
]
