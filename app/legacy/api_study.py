"""Study routes (P2 Task 5): start a deep-read job; compare papers synchronously.

``POST /api/papers/{paper_id}/interpret`` creates a ``kind='interpret'``
row in the shared ``import_jobs`` table (polled via the existing
``GET /api/import/jobs/{id}``) and launches ``run_interpretation`` as an
asyncio background task with a *dedicated* sqlite connection — same shape as
the folder-import route in ``app.api.import``.

``POST /api/compare`` runs the whole comparison inline and returns matrix +
citations. Validation lives here, not in the engine (contract 4): the id
list is de-duplicated first (position numbering follows the deduped order),
then 2–5 papers are required, and a missing id surfaces as the engine's
ValueError → 400. An empty question string counts as "no question". The
comparison runs on a *dedicated* short-lived sqlite connection (never the
request-loop's ``app.state.db``): compare_papers hands its connection to
``asyncio.to_thread`` workers, and interleaving those transactions with
request handlers sharing one connection is unsafe (P1 job pattern — see
``app.core.db.get_conn``).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..core.db import get_conn
from ..ingest.batch import run_interpretation
from .study.compare import compare_papers
from .errors import (
    KNOWN_INGEST_ERRORS,
    KNOWN_STUDY_ERRORS,
    ingest_http_error,
    require_rag_stack,
    study_http_error,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["study"])

#: asyncio only keeps *referenced* tasks alive; holding them here also gives
#: the done-callback a place to log a crashed job it would otherwise swallow.
#: (Same pattern as app.api.import._RUNNING_JOBS.)
_RUNNING_JOBS: set[asyncio.Task] = set()


class CompareRequest(BaseModel):
    paper_ids: list[int]
    question: str | None = None


def _job_finished(task: asyncio.Task) -> None:
    _RUNNING_JOBS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("interpret job task crashed: %s", task.exception())


@router.post("/papers/{paper_id}/interpret")
async def start_interpretation(paper_id: int, request: Request) -> dict:
    """Start deep-reading one paper in the background; returns {"job_id": int}.

    404 when the paper does not exist; 409 while an earlier interpret job
    for the same paper is still pending/running. Progress is polled on the
    shared job endpoint; the results land in the notes routes.
    """
    state = request.app.state
    db = state.db
    if (
        db.execute(
            "SELECT 1 FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        is None
    ):
        raise HTTPException(
            status_code=404, detail=f"paper {paper_id} not found"
        )
    if (
        db.execute(
            "SELECT 1 FROM import_jobs WHERE kind = 'interpret'"
            " AND path = ? AND status IN ('pending', 'running')",
            (f"interpret:{paper_id}",),
        ).fetchone()
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail=f"paper {paper_id} already has a running interpretation job",
        )

    # dedicated connection for the background job (check_same_thread=False
    # via get_conn — interpret_paper's sqlite work runs on to_thread workers)
    job_db = get_conn(state.settings)
    try:
        cursor = job_db.execute(
            "INSERT INTO import_jobs (path, kind, total, status)"
            " VALUES (?, 'interpret', 1, 'running')",
            (f"interpret:{paper_id}",),
        )
        job_id = int(cursor.lastrowid)
        job_db.commit()
    except Exception:
        job_db.close()
        raise

    task = asyncio.create_task(
        run_interpretation(job_id, paper_id, job_db, state.gateway)
    )
    _RUNNING_JOBS.add(task)
    task.add_done_callback(_job_finished)
    return {"job_id": job_id}


@router.post("/compare")
async def compare(body: CompareRequest, request: Request) -> dict:
    """Compare 2–5 papers (question optional); returns matrix + citations.

    Validation order: de-duplicate the id list (keeps first occurrence, so
    the [P{n}] numbering follows the deduped order), then require 2–5
    papers, then let the engine's missing-paper ValueError become a 400.
    The whole comparison is awaited inline — a single-user app can afford a
    request-scoped slow call, and it keeps the response contract simple.
    """
    require_rag_stack(request)
    state = request.app.state

    ids: list[int] = []
    for paper_id in body.paper_ids:
        if paper_id not in ids:
            ids.append(paper_id)
    if not 2 <= len(ids) <= 5:
        raise HTTPException(
            status_code=400,
            detail=(
                "paper_ids must contain 2 to 5 distinct papers"
                f" (got {len(ids)} after de-duplication)"
            ),
        )
    # empty string counts as no question
    question = (body.question or "").strip() or None

    # dedicated short-lived connection (P1 job pattern): compare_papers runs
    # its sqlite reads on to_thread workers — the shared app.state.db must
    # not be handed across that boundary
    compare_db = get_conn(state.settings)
    try:
        return await compare_papers(
            ids,
            question,
            db=compare_db,
            embedder=state.embedder,
            store=state.store,
            gateway=state.gateway,
        )
    except KNOWN_STUDY_ERRORS as exc:
        raise study_http_error(exc) from exc
    except KNOWN_INGEST_ERRORS as exc:
        raise ingest_http_error(exc) from exc
    finally:
        compare_db.close()
