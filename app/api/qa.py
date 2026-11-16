"""QA route: embed the question, retrieve excerpts, answer with citations."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..rag.vector_store import SearchHit
from . import KNOWN_INGEST_ERRORS, ingest_http_error, require_rag_stack

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qa", tags=["qa"])

TOP_K = 8
MAX_TOKENS = 2048
NO_CONTENT_ANSWER = "未找到相关内容"

_SYSTEM_PROMPT = (
    "You are a research assistant. Answer the user's question about their "
    "papers using ONLY the provided excerpts. Whenever an excerpt supports a "
    "statement, cite it by its [n] marker (e.g. [1])."
)

_MARKERS_RE = re.compile(r"\[(\d+)\]")


class QARequest(BaseModel):
    question: str
    paper_id: int | None = None


@router.post("")
async def answer_question(body: QARequest, request: Request) -> dict:
    """RAG answer over the library (optionally scoped to one paper).

    embed(question) → store.search(top_k=8) → numbered excerpts prompt →
    gateway.chat(tier="strong") → the answer's [n] markers map back to the
    excerpts' page/quote. With no retrieved excerpts there is nothing to ask
    the LLM about, so the no-content answer is returned without a gateway
    call. The gateway already enforces its own httpx timeout per operation,
    so no extra timeout is wrapped around it here.
    """
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")
    require_rag_stack(request)

    state = request.app.state
    try:
        query_vector = state.embedder.embed([question])[0]
        hits = state.store.search(query_vector, top_k=TOP_K, paper_id=body.paper_id)
    except KNOWN_INGEST_ERRORS as exc:
        raise ingest_http_error(exc) from exc

    if not hits:
        return {"answer": NO_CONTENT_ANSWER, "citations": []}

    excerpts = "\n\n".join(
        f"[{i}] (paper {hit.paper_id}, page {hit.page}, section {hit.section})\n"
        f"{hit.text}"
        for i, hit in enumerate(hits, start=1)
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Question: {question}\n\nExcerpts:\n\n{excerpts}",
        },
    ]
    try:
        reply = await state.gateway.chat(
            messages, tier="strong", max_tokens=MAX_TOKENS
        )
    except Exception:
        logger.exception("gateway call failed during qa")
        raise HTTPException(status_code=500, detail="llm gateway failed to answer")

    answer = str(reply["text"])
    return {"answer": answer, "citations": _map_citations(answer, hits)}


def _map_citations(answer: str, hits: list[SearchHit]) -> list[dict]:
    """Map the answer's [n] markers back to their excerpts (order preserved,
    duplicates collapsed, out-of-range indexes ignored). An answer with no
    usable markers attaches every retrieved excerpt instead (≤ TOP_K)."""
    seen: set[int] = set()
    cited: list[int] = []
    for match in _MARKERS_RE.finditer(answer):
        index = int(match.group(1))
        if 1 <= index <= len(hits) and index not in seen:
            seen.add(index)
            cited.append(index)
    if not cited:
        cited = list(range(1, len(hits) + 1))
    return [
        {
            "paper_id": hits[i - 1].paper_id,
            "page": hits[i - 1].page,
            "quote": hits[i - 1].text,
        }
        for i in cited
    ]
