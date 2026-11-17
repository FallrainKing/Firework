"""SQL for research schedules."""
from __future__ import annotations

import sqlite3


def list_schedules(db: sqlite3.Connection):
    return db.execute(
        'SELECT s.*,c.title AS session_title FROM research_schedules s JOIN conversations c ON c.id=s.conversation_id ORDER BY s.id DESC'
    ).fetchall()


def find_schedule(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT * FROM research_schedules WHERE id=?', (ident,)).fetchone()


def insert_schedule(db, title, conversation_id, prompt, interval_hours, enabled, next_at):
    return db.execute(
        'INSERT INTO research_schedules(title,conversation_id,prompt,interval_hours,enabled,next_at) VALUES (?,?,?,?,?,?)',
        (title, conversation_id, prompt, interval_hours, enabled, next_at),
    )


def set_enabled(db: sqlite3.Connection, ident: int, enabled: bool, next_at: str) -> None:
    db.execute('UPDATE research_schedules SET enabled=?,next_at=? WHERE id=?', (enabled, next_at, ident))


def set_last_run(db: sqlite3.Connection, ident: int, run_id: str, next_at: str) -> None:
    db.execute('UPDATE research_schedules SET last_run_id=?,next_at=? WHERE id=?', (run_id, next_at, ident))


def advance_next(db: sqlite3.Connection, ident: int, next_at: str) -> None:
    db.execute('UPDATE research_schedules SET next_at=? WHERE id=?', (next_at, ident))


def due_schedules(db: sqlite3.Connection):
    return db.execute("SELECT * FROM research_schedules WHERE enabled=1 AND next_at<=datetime('now')").fetchall()


def session_pdfs(db: sqlite3.Connection, conversation_id: int):
    return db.execute(
        'SELECT p.pdf_path FROM papers p JOIN conversation_papers cp ON cp.paper_id=p.id WHERE cp.conversation_id=?',
        (conversation_id,),
    ).fetchall()
