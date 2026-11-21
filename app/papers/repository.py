"""SQL for paper cards, collections and metadata edits."""
from __future__ import annotations

import sqlite3


def find_paper(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT * FROM papers WHERE id=?', (ident,)).fetchone()


def paper_exists(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT 1 FROM papers WHERE id=? AND deleted_at IS NULL', (ident,)).fetchone()


def list_collections(db: sqlite3.Connection):
    return db.execute(
        'SELECT c.*,(SELECT count(*) FROM paper_collection_items x WHERE x.collection_id=c.id) AS count FROM paper_collections c ORDER BY c.id'
    ).fetchall()


def insert_collection(db: sqlite3.Connection, name: str, parent_id: int | None = None):
    return db.execute('INSERT INTO paper_collections(name,parent_id) VALUES (?,?)', (name,parent_id))


def collection_exists(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT 1 FROM paper_collections WHERE id=?', (ident,)).fetchone()


def paper_collections(db: sqlite3.Connection, pid: int):
    return db.execute(
        'SELECT c.id,c.name FROM paper_collections c JOIN paper_collection_items x ON x.collection_id=c.id WHERE x.paper_id=? ORDER BY c.id',
        (pid,),
    ).fetchall()


READING_STATUSES = ('unread', 'reading', 'read')


def _search_where(q, collection_id, reading_status=None, trashed=False):
    if reading_status is not None and reading_status not in READING_STATUSES:
        raise ValueError('reading_status must be unread, reading or read')
    where = " WHERE (instr(lower(coalesce(p.title,'')),lower(?))>0 OR instr(lower(coalesce(p.abstract,'')),lower(?))>0 OR instr(lower(coalesce(p.authors,'')),lower(?))>0 OR instr(lower(p.affiliations),lower(?))>0 OR instr(lower(p.brief_summary),lower(?))>0)"
    args = [q] * 5
    where += ' AND p.deleted_at IS ' + ('NOT NULL' if trashed else 'NULL')
    if collection_id is not None:
        if collection_id == 0:
            where += ' AND NOT EXISTS (SELECT 1 FROM paper_collection_items x WHERE x.paper_id=p.id)'
        else:
            where += ' AND EXISTS(SELECT 1 FROM paper_collection_items x WHERE x.paper_id=p.id AND x.collection_id IN (WITH RECURSIVE tree(id) AS (SELECT id FROM paper_collections WHERE id=? UNION SELECT c.id FROM paper_collections c JOIN tree t ON c.parent_id=t.id) SELECT id FROM tree))'
            args.append(collection_id)
    if reading_status is not None:
        where += " AND (CASE WHEN EXISTS(SELECT 1 FROM conversation_papers cp JOIN conversations c ON c.id=cp.conversation_id JOIN agent_runs ar ON ar.conversation_id=c.id WHERE cp.paper_id=p.id AND c.skill='paper_read' AND ar.status='succeeded') THEN 'read' WHEN EXISTS(SELECT 1 FROM conversation_papers cp JOIN conversations c ON c.id=cp.conversation_id WHERE cp.paper_id=p.id AND c.skill='paper_read') THEN 'reading' ELSE 'unread' END)=?"
        args.append(reading_status)
    return where, args


def reading_status(db: sqlite3.Connection, pid: int) -> str:
    if db.execute("SELECT 1 FROM conversation_papers cp JOIN conversations c ON c.id=cp.conversation_id JOIN agent_runs ar ON ar.conversation_id=c.id WHERE cp.paper_id=? AND c.skill='paper_read' AND ar.status='succeeded' LIMIT 1", (pid,)).fetchone():
        return 'read'
    if db.execute("SELECT 1 FROM conversation_papers cp JOIN conversations c ON c.id=cp.conversation_id WHERE cp.paper_id=? AND c.skill='paper_read' LIMIT 1", (pid,)).fetchone():
        return 'reading'
    return 'unread'


def count_papers(db: sqlite3.Connection, q: str, collection_id: int | None, reading_status: str | None = None, trashed=False) -> int:
    where, args = _search_where(q, collection_id, reading_status, trashed)
    return db.execute('SELECT count(*) FROM papers p' + where, args).fetchone()[0]


def search_papers(db: sqlite3.Connection, q: str, collection_id: int | None, limit: int, offset: int, reading_status: str | None = None, trashed=False):
    where, args = _search_where(q, collection_id, reading_status, trashed)
    return db.execute(
        'SELECT p.* FROM papers p' + where + ' ORDER BY p.id DESC LIMIT ? OFFSET ?',
        args + [limit, offset],
    ).fetchall()


def update_paper_field(db: sqlite3.Connection, pid: int, key: str, value) -> None:
    db.execute(f'UPDATE papers SET {key}=? WHERE id=?', (value, pid))


def set_affiliation_source(db: sqlite3.Connection, pid: int, source: str) -> None:
    db.execute("UPDATE papers SET affiliation_source=? WHERE id=?", (source, pid))


def set_summary_source(db: sqlite3.Connection, pid: int, source: str) -> None:
    db.execute("UPDATE papers SET summary_source=? WHERE id=?", (source, pid))


def bump_metadata_version(db: sqlite3.Connection, pid: int) -> None:
    db.execute('UPDATE papers SET metadata_version=metadata_version+1 WHERE id=?', (pid,))


def replace_collection_items(db: sqlite3.Connection, pid: int, ids) -> None:
    db.execute('DELETE FROM paper_collection_items WHERE paper_id=?', (pid,))
    db.executemany(
        'INSERT INTO paper_collection_items(collection_id,paper_id) VALUES (?,?)',
        [(i, pid) for i in set(ids)],
    )


def add_collection_item(db: sqlite3.Connection, collection_id: int, pid: int) -> None:
    db.execute('INSERT OR IGNORE INTO paper_collection_items(collection_id,paper_id) VALUES (?,?)', (collection_id, pid))


def refresh_affiliations(db: sqlite3.Connection, pid: int, affiliations_json: str, source: str, expected_version: int) -> None:
    db.execute(
        'UPDATE papers SET affiliations=?,affiliation_source=?,metadata_version=metadata_version+1 WHERE id=? AND metadata_version=?',
        (affiliations_json, source, pid, expected_version),
    )
