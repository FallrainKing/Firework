"""SQL for import requests."""
from __future__ import annotations

import sqlite3


def find_import(db: sqlite3.Connection, ident: str):
    return db.execute('SELECT * FROM import_requests WHERE id=?', (ident,)).fetchone()


def find_import_by_key(db: sqlite3.Connection, request_key: str):
    return db.execute('SELECT * FROM import_requests WHERE request_key=?', (request_key,)).fetchone()


def list_imports(db: sqlite3.Connection):
    return db.execute('SELECT * FROM import_requests ORDER BY created_at DESC,rowid DESC LIMIT 40').fetchall()


def insert_source_import(db, ident, request_key, channel, source_value, collection_id, target_paper_id) -> None:
    db.execute(
        'INSERT INTO import_requests(id,request_key,channel,source_value,collection_id,target_paper_id) VALUES (?,?,?,?,?,?)',
        (ident, request_key, channel, source_value, collection_id, target_paper_id),
    )


def insert_upload_import(db, ident, request_key, filename, file_hash, collection_id, target_paper_id) -> None:
    db.execute(
        "INSERT INTO import_requests(id,request_key,channel,source_value,original_filename,file_hash,collection_id,target_paper_id) VALUES (?,?,'upload',?,?,?,?,?)",
        (ident, request_key, 'uploaded_pdf', filename, file_hash, collection_id, target_paper_id),
    )


def set_conversation(db: sqlite3.Connection, ident: str, sid: int) -> None:
    db.execute('UPDATE import_requests SET conversation_id=? WHERE id=?', (sid, ident))


def set_pending(db: sqlite3.Connection, ident: str, run_id: str) -> None:
    db.execute(
        "UPDATE import_requests SET status='pending',run_id=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (run_id, ident),
    )


def set_failed(db: sqlite3.Connection, ident: str, error: str) -> None:
    db.execute(
        "UPDATE import_requests SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (error, ident),
    )


def set_running(db: sqlite3.Connection, ident: str) -> None:
    db.execute(
        "UPDATE import_requests SET status='running' WHERE id=? AND status IN ('pending','failed')",
        (ident,),
    )


def set_completed(db: sqlite3.Connection, ident: str, paper_id: int, message: str) -> None:
    db.execute(
        "UPDATE import_requests SET status='completed',paper_id=?,message=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (paper_id, message, ident),
    )
