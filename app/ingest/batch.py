"""Background folder-import job (Task 7).

Walks one directory — non-recursive, ``*.pdf`` only — and ingests every file
through the standard upload pipeline. Progress is written to the job's
``import_jobs`` row after every file (done/failed/errors), so the API can
poll a live job. A file that duplicates something already in the library
counts as done; a file that raises is recorded in ``errors`` and the job
moves on to the next one.

The caller hands this coroutine a *dedicated* sqlite connection (never one
shared with request handlers): the job runs as an ``asyncio`` background
task and must not interleave transactions with request handlers on the same
connection. The job closes that connection when it finishes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from ..rag.embedder import Embedder
from ..rag.vector_store import VectorStore
from .dedup import find_duplicate
from .pipeline import ingest_from_upload

if TYPE_CHECKING:
    from ..llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


def _update_job(
    db: sqlite3.Connection,
    job_id: int,
    *,
    total: int,
    done: int,
    failed: int,
    errors: list[dict],
    status: str,
) -> None:
    """Write the job's live counters as one UPDATE (readers never see a torn
    mix of two files' progress; WAL lets concurrent readers proceed)."""
    db.execute(
        "UPDATE import_jobs SET total=?, done=?, failed=?, errors=?, status=?"
        " WHERE id=?",
        (total, done, failed, json.dumps(errors), status, job_id),
    )
    db.commit()


async def import_folder(
    path: str,
    job_id: int,
    db: sqlite3.Connection,
    embedder: Embedder,
    store: VectorStore,
    gateway: "LLMGateway",
    data_dir: Path,
) -> None:
    """Import every ``*.pdf`` directly inside ``path`` into the library."""
    folder = Path(path)
    pdfs = sorted(folder.glob("*.pdf"))  # non-recursive
    total = len(pdfs)
    done = failed = 0
    errors: list[dict] = []

    # total is written up-front so a poller sees the real file count even
    # before the first file completes
    _update_job(db, job_id, total=total, done=0, failed=0, errors=[], status="running")
    try:
        for pdf in pdfs:
            try:
                # cheap pre-check on the filename-derived title (the fallback
                # metadata for imports); ingest_from_upload re-checks the
                # LLM-extracted title internally, so a miss here is harmless
                duplicate = await find_duplicate(
                    pdf.stem, embedder=embedder, store=store, db=db
                )
                if duplicate is None:
                    # disk reads go through to_thread too: a slow/large file
                    # must not stall the loop the progress API runs on
                    data = await asyncio.to_thread(pdf.read_bytes)
                    await ingest_from_upload(
                        data,
                        pdf.name,
                        gateway=gateway,
                        db=db,
                        embedder=embedder,
                        store=store,
                        data_dir=data_dir,
                    )
            except Exception as exc:  # noqa: BLE001 — one bad file never kills the job
                failed += 1
                errors.append({"file": pdf.name, "error": str(exc)})
                logger.warning("batch import: %s failed: %s", pdf.name, exc)
            else:
                done += 1
            _update_job(
                db, job_id, total=total, done=done, failed=failed,
                errors=errors, status="running",
            )
    except BaseException:
        # cancelled or crashed outright: mark the job failed, keep the
        # counters written so far, then let the error propagate
        _update_job(
            db, job_id, total=total, done=done, failed=failed,
            errors=errors, status="failed",
        )
        raise
    else:
        _update_job(
            db, job_id, total=total, done=done, failed=failed,
            errors=errors, status="completed",
        )
    finally:
        db.close()
