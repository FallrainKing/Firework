"""Paper routes: multipart upload, arXiv ingest, library listing."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..ingest.pipeline import ingest_arxiv, ingest_from_upload
from .errors import KNOWN_INGEST_ERRORS, ingest_http_error, require_rag_stack

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/papers", tags=["papers"])


class ArxivRequest(BaseModel):
    url: str


@router.post("/upload")
async def upload_paper(request: Request, file: UploadFile = File(...)) -> dict:
    """Ingest an uploaded PDF; a duplicate returns the existing paper_id (200).

    Bad PDF bytes raise through the pipeline unwrapped (pymupdf errors,
    ValueErrors) and are mapped here to 400 with the pipeline's message.
    """
    require_rag_stack(request)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    state = request.app.state
    try:
        paper_id = await ingest_from_upload(
            data,
            file.filename or "upload.pdf",
            gateway=state.gateway,
            db=state.db,
            embedder=state.embedder,
            store=state.store,
            data_dir=state.settings.data_dir,
        )
    except KNOWN_INGEST_ERRORS as exc:
        raise ingest_http_error(exc) from exc
    except Exception:
        logger.exception("upload ingest failed unexpectedly")
        raise HTTPException(
            status_code=500, detail="internal error while ingesting the upload"
        )
    return {"paper_id": paper_id}


@router.post("/arxiv")
async def ingest_arxiv_paper(body: ArxivRequest, request: Request) -> dict:
    """Fetch and ingest an arXiv paper by abs/pdf URL or bare id."""
    require_rag_stack(request)
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url must not be empty")

    state = request.app.state
    try:
        paper_id = await ingest_arxiv(
            url,
            db=state.db,
            embedder=state.embedder,
            store=state.store,
            data_dir=state.settings.data_dir,
        )
    except KNOWN_INGEST_ERRORS as exc:
        raise ingest_http_error(exc) from exc
    except Exception:
        logger.exception("arxiv ingest failed unexpectedly")
        raise HTTPException(
            status_code=500, detail="internal error while ingesting the arxiv paper"
        )
    return {"paper_id": paper_id}


@router.get("")
async def list_papers(request: Request) -> dict:
    """Every paper in the library, newest first.

    async on purpose: sync endpoints run in Starlette's threadpool, which
    would touch the lifespan's sqlite connection from another thread.
    """
    rows = request.app.state.db.execute(
        "SELECT id, arxiv_id, title, authors, abstract, categories, source,"
        " status, pdf_path, created_at"
        " FROM papers ORDER BY created_at DESC, id DESC"
    ).fetchall()

    papers = []
    for row in rows:
        paper = dict(row)
        for key in ("authors", "categories"):  # stored as JSON strings
            try:
                paper[key] = json.loads(paper[key]) if paper[key] else []
            except (TypeError, ValueError):
                paper[key] = []
        papers.append(paper)
    return {"papers": papers}
