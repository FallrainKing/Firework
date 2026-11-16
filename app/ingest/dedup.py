"""Cross-source duplicate detection (Task 6).

A duplicate is detected in two stages:

1. exact match on the normalized title (lower-cased, all whitespace and
   punctuation stripped), and
2. a vector fallback: the query title is embedded and searched against the
   ingested chunk vectors; a top-1 similarity at or above ``threshold``
   (default 0.92, bge-m3 cosine) counts as the same paper.

Both stages work across sources: an uploaded PDF and the same paper arriving
from an arXiv feed resolve to the same existing row.
"""

from __future__ import annotations

import re
import sqlite3

from ..rag.embedder import Embedder
from ..rag.vector_store import VectorStore


def normalize_title(title: str) -> str:
    """Reduce a title to a comparison key: lower-cased alphanumeric run.

    All whitespace and punctuation is removed, so ``"Diffusion  Policy:"``
    and ``"diffusion policy"`` share one key. Unicode letters and digits
    (e.g. Chinese titles) are kept.
    """
    return re.sub(r"[\W_]+", "", (title or "").lower(), flags=re.UNICODE)


def _paper_dict(db: sqlite3.Connection, paper_id: int) -> dict | None:
    row = db.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    return dict(row) if row is not None else None


async def find_duplicate(
    title: str,
    *,
    embedder: Embedder,
    store: VectorStore,
    db: sqlite3.Connection,
    threshold: float = 0.92,
) -> dict | None:
    """Return the already-ingested paper matching ``title``, else None.

    Stage 1 compares the normalized title against every stored title (an
    exact hit skips the embedding call). Stage 2 embeds the title and takes
    the top-1 chunk hit; ``score >= threshold`` returns that paper's full row
    as a dict. A vector hit whose paper_id no longer exists in SQLite (e.g.
    an orphaned point) is treated as no duplicate.
    """
    if not (title or "").strip():
        return None  # nothing to compare against — never a duplicate

    key = normalize_title(title)
    if key:
        for row in db.execute("SELECT id, title FROM papers"):
            if normalize_title(row["title"] or "") == key:
                return _paper_dict(db, row["id"])

    hits = store.search(embedder.embed([title])[0], top_k=1)
    if hits and hits[0].score >= threshold:
        return _paper_dict(db, hits[0].paper_id)
    return None
