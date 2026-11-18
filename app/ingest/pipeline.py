"""Single-paper ingest pipeline (Task 6).

One paper travels: PDF file → pages → sections → chunks → (batch) embeddings
→ SQLite ``papers``/``chunks_meta`` rows + Qdrant points + PDF stored under
``data_dir/papers/{paper_id}.pdf``.

Transaction semantics: the SQLite writes (papers + chunks_meta) and the
Qdrant upsert happen such that the SQLite transaction is only committed
after the vector upsert succeeded; a vector failure rolls SQLite back so no
half-ingested state survives (the staged PDF copy is removed too — the PDF
is only renamed into its final path after the commit, so a failed run never
overwrites a previously ingested copy).
The one deliberate exception is the *pre-transaction* deletion of a previous
ingest's vectors (``store.delete_paper``): if the run then fails, the old
points are gone while SQLite still describes them — accepted because a
re-ingest restores them, and a duplicate entry never gets this far.

Entry points dedupe before doing any work: ``ingest_arxiv`` returns the
existing paper_id when the paper is already in the library (see
:func:`app.ingest.dedup.find_duplicate`). Upload metadata is deterministic
(pymupdf embedded metadata / filename fallback) in ``app.imports.pipeline``;
no LLM is involved in ingestion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path

import httpx

from ..rag.chunker import Chunk, chunk_sections
from ..rag.embedder import Embedder
from ..rag.pdf_parser import extract_pages, split_sections
from ..rag.vector_store import ChunkPoint, VectorStore
from .dedup import find_duplicate, normalize_title
from .metadata import extract_arxiv_id, fetch_arxiv_metadata


logger = logging.getLogger(__name__)

# arXiv PDF download limits (streamed, never fully buffered past this size).
ARXIV_PDF_URL = "https://arxiv.org/pdf/{id}"
ARXIV_PDF_TIMEOUT = httpx.Timeout(60.0)
ARXIV_PDF_MAX_BYTES = 50 * 1024 * 1024



class PdfTooLargeError(RuntimeError):
    """The arXiv PDF download exceeded the 50MB cap (a known-bad input)."""


def _parse_and_embed(
    pdf_path: Path, embedder: Embedder
) -> tuple[list[Chunk], list[list[float]]]:
    """Parse + chunk + embed one PDF. Pure CPU work: touches no sqlite
    connection and no vector store, so it is safe to run on a worker
    thread (see :func:`ingest_paper`)."""
    chunks = chunk_sections(split_sections(extract_pages(pdf_path)))
    # one batch call for the whole paper, never per-chunk
    vectors = embedder.embed([chunk.text for chunk in chunks])
    return chunks, vectors


async def download_arxiv_pdf(arxiv_id: str) -> bytes:
    """Download ``https://arxiv.org/pdf/{id}`` as bytes (streamed, size-capped).

    Raises ``PdfTooLargeError`` when the response body exceeds the 50MB
    limit, and ``httpx.HTTPStatusError`` for non-2xx responses.
    """
    url = ARXIV_PDF_URL.format(id=arxiv_id)
    parts: list[bytes] = []
    total = 0
    async with httpx.AsyncClient(timeout=ARXIV_PDF_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > ARXIV_PDF_MAX_BYTES:
                    raise PdfTooLargeError(
                        f"arXiv PDF {arxiv_id!r} exceeds the "
                        f"{ARXIV_PDF_MAX_BYTES // (1024 * 1024)}MB limit"
                    )
                parts.append(chunk)
    return b"".join(parts)


def _find_existing_paper(
    db: sqlite3.Connection, arxiv_id: str | None, title: str
) -> int | None:
    """Paper row already present for this arxiv_id / normalized title."""
    if arxiv_id:
        row = db.execute(
            "SELECT id FROM papers WHERE arxiv_id=?", (arxiv_id,)
        ).fetchone()
        if row is not None:
            return row["id"]
    key = normalize_title(title)
    if not key:
        return None
    for row in db.execute("SELECT id, title FROM papers"):
        if normalize_title(row["title"] or "") == key:
            return row["id"]
    return None


async def ingest_paper(
    pdf_path: Path,
    *,
    source: str,
    arxiv_id: str | None,
    title: str,
    authors: list[str],
    abstract: str,
    categories: list[str],
    db: sqlite3.Connection,
    embedder: Embedder,
    store: VectorStore,
    data_dir: Path,
    existing_paper_id: int | None = None,
) -> int:
    """Ingest one PDF end-to-end and return its paper_id.

    Re-ingesting a paper that is already present (same arxiv_id or same
    normalized title) reuses its row: the old vectors are deleted first
    (``store.delete_paper``, before the transaction, so a stale tail chunk
    can never survive a re-ingest), then the new chunks are written.
    """
    # parsing + chunking + embedding is CPU-bound and can take seconds per
    # paper — offload it so the event loop keeps serving requests during a
    # long ingest. The offloaded work touches no sqlite connection and no
    # vector store; the transaction below stays on the event loop's thread
    # with unchanged semantics.
    chunks, vectors = await asyncio.to_thread(_parse_and_embed, pdf_path, embedder)

    existing_id = existing_paper_id if existing_paper_id is not None else _find_existing_paper(db, arxiv_id, title)
    if existing_paper_id is not None and db.execute('SELECT 1 FROM papers WHERE id=?',(existing_paper_id,)).fetchone() is None:
        raise ValueError('Target paper does not exist')
    if existing_id is not None:
        store.delete_paper(existing_id)  # idempotent; see module docstring

    papers_dir = Path(data_dir) / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    staged: Path | None = None
    final_pdf: Path | None = None
    try:
        if existing_id is None:
            cursor = db.execute(
                "INSERT INTO papers (arxiv_id, title, authors, abstract,"
                " categories, source) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    arxiv_id,
                    title,
                    json.dumps(authors),
                    abstract,
                    json.dumps(categories),
                    source,
                ),
            )
            paper_id = int(cursor.lastrowid)
        else:
            paper_id = existing_id
            db.execute("DELETE FROM chunks_meta WHERE paper_id=?", (paper_id,))
            db.execute(
                "UPDATE papers SET arxiv_id=?, title=?, authors=?, abstract=?,"
                " categories=?, source=? WHERE id=?",
                (
                    arxiv_id,
                    title,
                    json.dumps(authors),
                    abstract,
                    json.dumps(categories),
                    source,
                    paper_id,
                ),
            )

        # the id is only known after the INSERT, so the copy happens here —
        # staged as a .tmp sibling and only renamed into place after the
        # commit, so a failed run (fresh or re-ingest) never leaves a new
        # PDF at the paper's final path while SQLite describes the old one
        final_pdf = papers_dir / f"{paper_id}.pdf"
        staged = papers_dir / f"{paper_id}.pdf.tmp"
        shutil.copyfile(pdf_path, staged)
        db.execute(
            "UPDATE papers SET pdf_path=? WHERE id=?", (str(final_pdf), paper_id)
        )

        for index, chunk in enumerate(chunks):
            db.execute(
                "INSERT INTO chunks_meta (paper_id, chunk_idx, section, page,"
                " text) VALUES (?, ?, ?, ?, ?)",
                (paper_id, index, chunk.section, chunk.page, chunk.text),
            )

        # vectors last: only a successful upsert lets the transaction commit
        store.upsert_chunks(
            [
                ChunkPoint(
                    paper_id=paper_id,
                    chunk_index=index,
                    text=chunk.text,
                    page=chunk.page,
                    section=chunk.section,
                    vector=vectors[index],
                )
                for index, chunk in enumerate(chunks)
            ]
        )
        db.commit()
        # everything succeeded — atomic same-dir rename puts the PDF in place
        staged.replace(final_pdf)
        staged = None
        return paper_id
    except Exception:
        db.rollback()
        # remove only the staged copy; a previously ingested PDF at the
        # final path (re-ingest) is never touched by a failed run
        if staged is not None:
            staged.unlink(missing_ok=True)
        raise


async def ingest_arxiv(
    url_or_id: str,
    *,
    db: sqlite3.Connection,
    embedder: Embedder,
    store: VectorStore,
    data_dir: Path,
) -> int:
    """Fetch, download and ingest an arXiv paper; dedupes before downloading."""
    arxiv_id = extract_arxiv_id(url_or_id)

    # strongest dedup first: a known arxiv_id needs no network round-trips
    row = db.execute(
        "SELECT id FROM papers WHERE arxiv_id=?", (arxiv_id,)
    ).fetchone()
    if row is not None:
        return row["id"]

    meta = await fetch_arxiv_metadata(url_or_id)
    duplicate = await find_duplicate(
        meta.title, embedder=embedder, store=store, db=db
    )
    if duplicate is not None:
        return duplicate["id"]

    pdf_bytes = await download_arxiv_pdf(arxiv_id)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)
    try:
        return await ingest_paper(
            tmp_path,
            source="arxiv",
            arxiv_id=arxiv_id,
            title=meta.title,
            authors=meta.authors,
            abstract=meta.abstract,
            categories=meta.categories,
            db=db,
            embedder=embedder,
            store=store,
            data_dir=data_dir,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
