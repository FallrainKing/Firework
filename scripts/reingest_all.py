#!/usr/bin/env python3
"""One-off: re-ingest every existing paper through the current parser/chunker.

Reads every ``papers`` row, drops its old qdrant points
(``store.delete_paper``) and re-runs :func:`app.ingest.pipeline.ingest_paper`
on the stored PDF. The pipeline's re-ingest path reuses (preserves) the
``paper_id``; metadata is taken unchanged from the row, so this only
re-derives pages → sections → chunks → embeddings. Purpose: apply the fixed
section-splitting heuristics to already-ingested papers so their chunks
carry correct ``section`` metadata.

Run from the repo root (the default ``data/`` is used; point ``QDRANT_URL``
at a reachable qdrant — in this deployment the container is not published
to the host, so use its bridge IP)::

    QDRANT_URL=http://<qdrant-container-ip>:6333 .venv/bin/python scripts/reingest_all.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qdrant_client import QdrantClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import get_conn  # noqa: E402
from app.ingest.pipeline import ingest_paper  # noqa: E402
from app.rag.embedder import Embedder  # noqa: E402
from app.rag.vector_store import VectorStore  # noqa: E402


def _host_pdf_path(row, settings: Settings) -> Path:
    """The stored PDF on this machine (container paths map onto data_dir)."""
    if row["pdf_path"]:
        candidate = Path(row["pdf_path"])
        if candidate.is_file():
            return candidate
    # "/app/data/papers/{id}.pdf" inside the container → data_dir on the host
    return settings.data_dir / "papers" / f"{row['id']}.pdf"


def main() -> None:
    settings = Settings.from_env()
    db = get_conn(settings)
    embedder = Embedder()
    store = VectorStore(QdrantClient(settings.qdrant_url))
    rows = db.execute("SELECT * FROM papers ORDER BY id").fetchall()
    print(f"re-ingesting {len(rows)} paper(s) from {settings.db_path}")

    for row in rows:
        pdf = _host_pdf_path(row, settings)
        if not pdf.is_file():
            print(f"[SKIP] paper {row['id']}: stored PDF missing ({pdf})")
            continue
        # drop the old points first; ingest_paper's re-ingest path then
        # rebuilds everything under the same paper_id
        removed = store.delete_paper(row["id"])
        paper_id = asyncio.run(
            ingest_paper(
                pdf,
                source=row["source"] or "upload",
                arxiv_id=row["arxiv_id"],
                title=row["title"] or pdf.stem,
                authors=json.loads(row["authors"] or "[]"),
                abstract=row["abstract"] or "",
                categories=json.loads(row["categories"] or "[]"),
                db=db,
                embedder=embedder,
                store=store,
                data_dir=settings.data_dir,
            )
        )
        assert paper_id == row["id"], "re-ingest must preserve the paper_id"
        sections = [
            r["section"]
            for r in db.execute(
                "SELECT DISTINCT section FROM chunks_meta WHERE paper_id=?"
                " ORDER BY section",
                (paper_id,),
            )
        ]
        print(
            f"[OK] paper {paper_id} ({row['title']!r}): removed {removed} old"
            f" points, sections now: {sections}"
        )

    print("done")


if __name__ == "__main__":
    main()
