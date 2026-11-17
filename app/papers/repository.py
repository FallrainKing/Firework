"""SQL for paper cards, collections and metadata edits."""
from __future__ import annotations

import sqlite3


def find_paper(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT * FROM papers WHERE id=?', (ident,)).fetchone()


def paper_exists(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT 1 FROM papers WHERE id=?', (ident,)).fetchone()


def list_collections(db: sqlite3.Connection):
    return db.execute(
        'SELECT c.*,(SELECT count(*) FROM paper_collection_items x WHERE x.collection_id=c.id) AS count FROM paper_collections c ORDER BY c.id'
    ).fetchall()


def insert_collection(db: sqlite3.Connection, name: str):
    return db.execute('INSERT INTO paper_collections(name) VALUES (?)', (name,))


def collection_exists(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT 1 FROM paper_collections WHERE id=?', (ident,)).fetchone()


def paper_collections(db: sqlite3.Connection, pid: int):
    return db.execute(
        'SELECT c.id,c.name FROM paper_collections c JOIN paper_collection_items x ON x.collection_id=c.id WHERE x.paper_id=? ORDER BY c.id',
        (pid,),
    ).fetchall()


def _search_where(q, collection_id):
    where = " WHERE (instr(lower(coalesce(p.title,'')),lower(?))>0 OR instr(lower(coalesce(p.abstract,'')),lower(?))>0 OR instr(lower(coalesce(p.authors,'')),lower(?))>0 OR instr(lower(p.affiliations),lower(?))>0 OR instr(lower(p.brief_summary),lower(?))>0)"
    args = [q] * 5
    if collection_id is not None:
        if collection_id == 0:
            where += ' AND NOT EXISTS (SELECT 1 FROM paper_collection_items x WHERE x.paper_id=p.id)'
        else:
            where += ' AND EXISTS(SELECT 1 FROM paper_collection_items x WHERE x.paper_id=p.id AND x.collection_id=?)'
            args.append(collection_id)
    return where, args


def count_papers(db: sqlite3.Connection, q: str, collection_id: int | None) -> int:
    where, args = _search_where(q, collection_id)
    return db.execute('SELECT count(*) FROM papers p' + where, args).fetchone()[0]


def search_papers(db: sqlite3.Connection, q: str, collection_id: int | None, limit: int, offset: int):
    where, args = _search_where(q, collection_id)
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
