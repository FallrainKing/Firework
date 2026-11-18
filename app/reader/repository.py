"""SQL for reader annotations, reading states and translation cache."""
from __future__ import annotations

import sqlite3


def find_paper(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT * FROM papers WHERE id=?', (ident,)).fetchone()


def is_linked(db: sqlite3.Connection, sid: int, pid: int):
    return db.execute(
        'SELECT 1 FROM conversation_papers WHERE conversation_id=? AND paper_id=?', (sid, pid)
    ).fetchone()


def list_annotations(db: sqlite3.Connection, pid: int):
    return db.execute(
        'SELECT * FROM reader_annotations WHERE paper_id=? AND deleted=0 ORDER BY page,created_at',
        (pid,),
    ).fetchall()


def insert_annotation(db, ident, paper_id, conversation_id, file_version, page, kind, quote, content, color, rects_json, points_json) -> None:
    db.execute(
        'INSERT INTO reader_annotations(id,paper_id,conversation_id,file_version,page,kind,quote,content,color,rects_json,points_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (ident, paper_id, conversation_id, file_version, page, kind, quote, content, color, rects_json, points_json),
    )


def find_annotation(db: sqlite3.Connection, ident: str):
    return db.execute('SELECT * FROM reader_annotations WHERE id=?', (ident,)).fetchone()


def update_annotation_field(db: sqlite3.Connection, ident: str, key: str, value) -> None:
    db.execute(
        f'UPDATE reader_annotations SET {key}=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (value, ident),
    )


def find_state(db: sqlite3.Connection, sid: int, pid: int):
    return db.execute(
        'SELECT * FROM reader_states WHERE conversation_id=? AND paper_id=?', (sid, pid)
    ).fetchone()


def upsert_state(db: sqlite3.Connection, sid: int, pid: int, page: int, zoom: str, tab: str) -> None:
    db.execute(
        'INSERT INTO reader_states(conversation_id,paper_id,page,zoom,tab) VALUES (?,?,?,?,?) ON CONFLICT(conversation_id,paper_id) DO UPDATE SET page=excluded.page,zoom=excluded.zoom,tab=excluded.tab,updated_at=CURRENT_TIMESTAMP',
        (sid, pid, page, zoom, tab),
    )


def list_translations(db: sqlite3.Connection, pid: int):
    return db.execute(
        'SELECT t.* FROM reader_translations t WHERE t.paper_id=? AND t.deleted=0 ORDER BY t.created_at DESC',
        (pid,),
    ).fetchall()


def find_cached_translation(db: sqlite3.Connection, pid: int, file_version: str, quote_hash: str, language: str):
    return db.execute(
        'SELECT t.* FROM reader_translations t WHERE t.paper_id=? AND t.file_version=? AND t.quote_hash=? AND t.language=?',
        (pid, file_version, quote_hash, language),
    ).fetchone()


def undelete_translation(db: sqlite3.Connection, ident: str) -> None:
    db.execute('UPDATE reader_translations SET deleted=0 WHERE id=?', (ident,))


def upsert_translation(db, ident, pid, sid, page, file_version, quote, quote_hash, run_id) -> None:
    db.execute(
        "INSERT INTO reader_translations(id,paper_id,conversation_id,page,file_version,quote,quote_hash,run_id) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(paper_id,file_version,quote_hash,language) DO UPDATE SET run_id=excluded.run_id,conversation_id=excluded.conversation_id,deleted=0",
        (ident, pid, sid, page, file_version, quote, quote_hash, run_id),
    )


def translation_exists(db: sqlite3.Connection, ident: str):
    return db.execute('SELECT 1 FROM reader_translations WHERE id=?', (ident,)).fetchone()


def set_translation_deleted(db: sqlite3.Connection, ident: str, deleted: bool) -> None:
    db.execute('UPDATE reader_translations SET deleted=? WHERE id=?', (deleted, ident))
