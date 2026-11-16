"""Folder-import routes: start a background batch job and poll its progress."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import get_conn
from ..ingest.batch import import_folder
from . import require_rag_stack

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/import", tags=["import"])

#: asyncio only keeps *referenced* tasks alive; holding them here also gives
#: the done-callback a place to log a crashed job it would otherwise swallow.
_RUNNING_JOBS: set[asyncio.Task] = set()


class FolderImportRequest(BaseModel):
    path: str


def _job_finished(task: asyncio.Task) -> None:
    _RUNNING_JOBS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("import job task crashed: %s", task.exception())


@router.post("/folder")
async def start_folder_import(body: FolderImportRequest, request: Request) -> dict:
    """Start importing every ``*.pdf`` in a local folder (non-recursive)."""
    require_rag_stack(request)
    state = request.app.state
    folder = Path(body.path).expanduser()
    if not folder.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"path does not exist or is not a directory: {body.path}",
        )

    # dedicated connection for the background job: it must not share the
    # request stack's sqlite connection (interleaved transactions)
    job_db = get_conn(state.settings)
    try:
        cursor = job_db.execute(
            "INSERT INTO import_jobs (path, total, status) VALUES (?, 0, 'running')",
            (str(folder),),
        )
        job_id = int(cursor.lastrowid)
        job_db.commit()
    except Exception:
        job_db.close()
        raise

    task = asyncio.create_task(
        import_folder(
            str(folder),
            job_id,
            job_db,
            state.embedder,
            state.store,
            state.gateway,
            state.settings.data_dir,
        )
    )
    _RUNNING_JOBS.add(task)
    task.add_done_callback(_job_finished)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_import_job(job_id: int, request: Request) -> dict:
    """Live progress of one import job (status: running | done).

    async on purpose: sync endpoints run in Starlette's threadpool, which
    would touch the lifespan's sqlite connection from another thread.
    """
    row = request.app.state.db.execute(
        "SELECT id, total, done, failed, errors, status FROM import_jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"import job {job_id} not found")

    try:
        errors = json.loads(row["errors"])
    except (TypeError, ValueError):
        errors = []
    if not isinstance(errors, list):
        errors = []

    # the DB row tracks pending|running|completed|failed; the API contract
    # collapses that to running|done (per-file failures live in `errors`)
    status = "running" if row["status"] in ("pending", "running") else "done"
    return {
        "id": row["id"],
        "total": row["total"],
        "done": row["done"],
        "failed": row["failed"],
        "errors": errors,
        "status": status,
    }
