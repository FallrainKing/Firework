"""Note routes: per-paper reading notes (list / create / delete).

Ruling R1: the notes table's column is ``note_type`` and its CHECK (see
app/migrations/0001_init.sql) currently allows section_analysis |
annotation | chat_summary. ``six_dim`` arrives with migration 0002 (Task 5),
which extends this constant in the same change — accepting it here, before
the CHECK knows it, would turn a validation-passing POST into an unhandled
IntegrityError (500) instead of a clean 400. Task 3's section analyses
reuse the DB's existing ``section_analysis`` and likewise extend this set
when they gain an API surface.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["notes"])

#: note types the create route accepts (see module docstring for why this
#: tracks, and only tracks, what the notes table's CHECK can store).
NOTE_TYPES = frozenset({"annotation", "chat_summary"})


class NoteCreate(BaseModel):
    note_type: str
    content: str


def _require_paper(db, paper_id: int) -> None:
    """404 unless the paper row exists (FKs are ON, so say so up front)."""
    if db.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"paper {paper_id} not found")


@router.get("/papers/{paper_id}/notes")
async def list_notes(paper_id: int, request: Request) -> dict:
    """Every note attached to a paper, newest first.

    async on purpose: sync endpoints run in Starlette's threadpool, which
    would touch the lifespan's sqlite connection from another thread.
    A paper with no notes (including one that does not exist) lists [].
    """
    rows = request.app.state.db.execute(
        "SELECT id, paper_id, note_type, content, created_at"
        " FROM notes WHERE paper_id = ?"
        " ORDER BY created_at DESC, id DESC",
        (paper_id,),
    ).fetchall()
    return {"notes": [dict(row) for row in rows]}


@router.post("/papers/{paper_id}/notes")
async def create_note(paper_id: int, body: NoteCreate, request: Request) -> dict:
    """Attach a note to a paper; returns the new note's id."""
    if body.note_type not in NOTE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"note_type must be one of {sorted(NOTE_TYPES)}",
        )
    db = request.app.state.db
    _require_paper(db, paper_id)
    cur = db.execute(
        "INSERT INTO notes (paper_id, note_type, content) VALUES (?, ?, ?)",
        (paper_id, body.note_type, body.content),
    )
    db.commit()
    return {"note_id": cur.lastrowid}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int, request: Request) -> dict:
    """Delete one note by id; 404 when it does not exist."""
    db = request.app.state.db
    cur = db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"note {note_id} not found")
    return {"deleted": True}
