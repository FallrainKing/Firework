"""SQL for workspace states, reader drafts and image attachment metadata."""
from __future__ import annotations

import sqlite3


def recent_reads(db: sqlite3.Connection):
    return db.execute(
        'SELECT r.paper_id,r.conversation_id,r.updated_at FROM reader_states r JOIN conversations c ON c.id=r.conversation_id WHERE c.archived=0 ORDER BY r.updated_at DESC,r.rowid DESC LIMIT 80'
    ).fetchall()


def find_workspace(db: sqlite3.Connection, ident: str):
    return db.execute('SELECT state_json FROM workspace_states WHERE id=?', (ident,)).fetchone()


def upsert_workspace(db: sqlite3.Connection, ident: str, state_json: str) -> None:
    db.execute(
        'INSERT INTO workspace_states(id,state_json) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP',
        (ident, state_json),
    )



def find_draft(db: sqlite3.Connection, sid: int, pid: int):
    return db.execute(
        'SELECT draft_json FROM reader_drafts WHERE conversation_id=? AND paper_id=?', (sid, pid)
    ).fetchone()


def upsert_draft(db: sqlite3.Connection, sid: int, pid: int, draft_json: str) -> None:
    db.execute(
        'INSERT INTO reader_drafts(conversation_id,paper_id,draft_json) VALUES (?,?,?) ON CONFLICT(conversation_id,paper_id) DO UPDATE SET draft_json=excluded.draft_json,updated_at=CURRENT_TIMESTAMP',
        (sid, pid, draft_json),
    )


def insert_attachment(db, ident, conversation_id, paper_id, filename, mime, size, width, height) -> None:
    db.execute(
        'INSERT INTO image_attachments(id,conversation_id,paper_id,filename,mime,size,width,height) VALUES (?,?,?,?,?,?,?,?)',
        (ident, conversation_id, paper_id, filename, mime, size, width, height),
    )


def find_attachment(db: sqlite3.Connection, ident: str):
    return db.execute('SELECT * FROM image_attachments WHERE id=?', (ident,)).fetchone()
