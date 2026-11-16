"""Single-paper ingest pipeline (Task 6).

One paper travels: PDF file → pages → sections → chunks → (batch) embeddings
→ SQLite ``papers``/``chunks_meta`` rows + Qdrant points + PDF stored under
``data_dir/papers/{paper_id}.pdf``.

Transaction semantics: the SQLite writes (papers + chunks_meta) and the
Qdrant upsert happen such that the SQLite transaction is only committed
after the vector upsert succeeded; a vector failure rolls SQLite back so no
half-ingested state survives (the already-copied PDF file is removed too).
The one deliberate exception is the *pre-transaction* deletion of a previous
ingest's vectors (``store.delete_paper``): if the run then fails, the old
points are gone while SQLite still describes them — accepted because a
re-ingest restores them, and a duplicate entry never gets this far.

Entry points dedupe before doing any work: ``ingest_from_upload`` and
``ingest_arxiv`` return the existing paper_id when the paper is already in
the library (see :func:`app.ingest.dedup.find_duplicate`).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from ..rag.chunker import chunk_sections
from ..rag.embedder import Embedder
from ..rag.pdf_parser import extract_pages, split_sections
from ..rag.vector_store import ChunkPoint, VectorStore
from .dedup import find_duplicate, normalize_title
from .metadata import extract_arxiv_id, fetch_arxiv_metadata

if TYPE_CHECKING:
    from ..llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

# arXiv PDF download limits (streamed, never fully buffered past this size).
ARXIV_PDF_URL = "https://arxiv.org/pdf/{id}"
ARXIV_PDF_TIMEOUT = httpx.Timeout(60.0)
ARXIV_PDF_MAX_BYTES = 50 * 1024 * 1024

# First-page snippet sent to the LLM for metadata extraction.
_FIRST_PAGE_CHARS = 1500
_FALLBACK_ABSTRACT_CHARS = 500

_METADATA_PROMPT = (
    "You are given the beginning of a research paper. Extract its "
    "bibliographic metadata. Reply with ONLY a strict JSON object of the "
    'exact form {"title": "...", "authors": ["..."], "abstract": "..."} '
    "— no markdown, no code fences, no commentary, no extra keys."
)


async def download_arxiv_pdf(arxiv_id: str) -> bytes:
    """Download ``https://arxiv.org/pdf/{id}`` as bytes (streamed, size-capped).

    Raises ``RuntimeError`` when the response body exceeds the 50MB limit,
    and ``httpx.HTTPStatusError`` for non-2xx responses.
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
                    raise RuntimeError(
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
) -> int:
    """Ingest one PDF end-to-end and return its paper_id.

    Re-ingesting a paper that is already present (same arxiv_id or same
    normalized title) reuses its row: the old vectors are deleted first
    (``store.delete_paper``, before the transaction, so a stale tail chunk
    can never survive a re-ingest), then the new chunks are written.
    """
    chunks = chunk_sections(split_sections(extract_pages(pdf_path)))
    # one batch call for the whole paper, never per-chunk
    vectors = embedder.embed([chunk.text for chunk in chunks])

    existing_id = _find_existing_paper(db, arxiv_id, title)
    if existing_id is not None:
        store.delete_paper(existing_id)  # idempotent; see module docstring

    papers_dir = Path(data_dir) / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    copied: Path | None = None
    copied_preexisted = False
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

        # the id is only known after the INSERT, so the copy happens here
        copied = papers_dir / f"{paper_id}.pdf"
        copied_preexisted = copied.exists()
        shutil.copyfile(pdf_path, copied)
        db.execute(
            "UPDATE papers SET pdf_path=? WHERE id=?", (str(copied), paper_id)
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
        return paper_id
    except Exception:
        db.rollback()
        # only remove the PDF this run created: on a re-ingest rollback the
        # previous ingest's copy must survive untouched
        if copied is not None and not copied_preexisted:
            copied.unlink(missing_ok=True)
        raise


async def _extract_metadata(
    gateway: "LLMGateway", first_page_text: str, filename: str
) -> tuple[str, list[str], str]:
    """(title, authors, abstract) for an uploaded PDF, via the fast LLM tier.

    The first ~1500 characters of page 1 are sent with a strict-JSON prompt.
    Any failure — request error, non-JSON reply, missing/ill-typed fields —
    falls back to filename-derived metadata rather than rejecting the paper.
    """
    fallback = (
        Path(filename).stem or "untitled",
        [],
        first_page_text[:_FALLBACK_ABSTRACT_CHARS].strip(),
    )
    if not first_page_text.strip():
        return fallback  # nothing for the LLM to read (e.g. scanned PDF)

    try:
        reply = await gateway.chat(
            [
                {"role": "system", "content": _METADATA_PROMPT},
                {"role": "user", "content": first_page_text[:_FIRST_PAGE_CHARS]},
            ],
            tier="fast",
        )
        raw = str(reply["text"]).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[\w+-]*\s*|\s*```$", "", raw)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("reply is not a JSON object")
        title = data.get("title")
        authors = data.get("authors")
        abstract = data.get("abstract")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("missing title")
        if not isinstance(authors, list):
            raise ValueError("missing authors")
        if not isinstance(abstract, str):
            raise ValueError("missing abstract")
        return title.strip(), [str(a) for a in authors], abstract.strip()
    except Exception as exc:  # noqa: BLE001 — any LLM hiccup degrades to fallback
        logger.warning("metadata extraction fell back for %r: %s", filename, exc)
        return fallback


async def ingest_from_upload(
    pdf_bytes: bytes,
    filename: str,
    *,
    gateway: "LLMGateway",
    db: sqlite3.Connection,
    embedder: Embedder,
    store: VectorStore,
    data_dir: Path,
) -> int:
    """Ingest a user-uploaded PDF; returns an existing id on a dedup hit."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)
    try:
        pages = extract_pages(tmp_path)
        first_page_text = pages[0].text if pages else ""
        title, authors, abstract = await _extract_metadata(
            gateway, first_page_text, filename
        )

        duplicate = await find_duplicate(
            title, embedder=embedder, store=store, db=db
        )
        if duplicate is not None:
            return duplicate["id"]

        return await ingest_paper(
            tmp_path,
            source="upload",
            arxiv_id=None,
            title=title,
            authors=authors,
            abstract=abstract,
            categories=[],
            db=db,
            embedder=embedder,
            store=store,
            data_dir=data_dir,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


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
