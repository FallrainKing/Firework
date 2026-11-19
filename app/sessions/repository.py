"""SQL for task sessions, templates and session categories."""
from __future__ import annotations

import sqlite3


def find_session(db: sqlite3.Connection, session_id: int):
    return db.execute(
        "SELECT * FROM conversations WHERE id=? AND module='agent'", (session_id,)
    ).fetchone()


def paper_ids(db: sqlite3.Connection, sid: int) -> list[int]:
    return [
        r[0]
        for r in db.execute(
            'SELECT paper_id FROM conversation_papers WHERE conversation_id=? ORDER BY paper_id',
            (sid,),
        )
    ]


def list_templates(db: sqlite3.Connection):
    return db.execute(
        "SELECT t.* FROM task_templates t "
        "LEFT JOIN skills s ON s.id=t.skill "
        "WHERE t.builtin=1 OR s.id IS NULL OR s.status='enabled' "
        "ORDER BY t.builtin DESC,t.rowid"
    ).fetchall()


def find_template(db: sqlite3.Connection, template_id: str):
    return db.execute('SELECT * FROM task_templates WHERE id=?', (template_id,)).fetchone()


def insert_template(db, ident, name, description, kind, skill, prompt) -> None:
    db.execute(
        'INSERT INTO task_templates(id,name,description,kind,skill,prompt) VALUES (?,?,?,?,?,?)',
        (ident, name, description, kind, skill, prompt),
    )


def list_categories(db: sqlite3.Connection):
    return db.execute(
        "SELECT s.id,s.name,(SELECT count(*) FROM conversations c WHERE c.category_id=s.id AND c.module='agent' AND c.archived=0) AS count FROM session_categories s ORDER BY s.id"
    ).fetchall()


def insert_category(db: sqlite3.Connection, name: str):
    return db.execute('INSERT INTO session_categories(name) VALUES (?)', (name,))


def category_exists(db: sqlite3.Connection, ident: int):
    return db.execute('SELECT 1 FROM session_categories WHERE id=?', (ident,)).fetchone()


def search_sessions(db, *, q, kind, paper_id, category_id, archived, limit, run_match_ids=()):
    sql = "SELECT c.* FROM conversations c WHERE c.module='agent' AND c.archived=?"
    args = [int(archived)]
    if paper_id is not None:
        sql += ' AND EXISTS(SELECT 1 FROM conversation_papers cp WHERE cp.conversation_id=c.id AND cp.paper_id=?)'
        args.append(paper_id)
    if kind:
        sql += ' AND c.kind=?'
        args.append(kind)
    if category_id is not None:
        sql += ' AND ' + ('c.category_id IS NULL' if category_id == 0 else 'c.category_id=?')
        if category_id:
            args.append(category_id)
    if q:
        # Run-content matches are resolved by agent.service (owns agent_runs).
        ids = list(run_match_ids)
        placeholders = ','.join('?' * len(ids)) if ids else 'NULL'
        sql += f' AND (instr(lower(c.title),lower(?))>0 OR c.id IN ({placeholders}))'
        args.append(q)
        args.extend(ids)
    return db.execute(
        sql + ' ORDER BY c.pinned DESC,c.updated_at DESC,c.id DESC LIMIT ?', args + [limit]
    ).fetchall()


def insert_session(db, *, title, kind, skill, template_id, category_id, native_session_id, draft_prompt,
                     skill_version_id=None):
    return db.execute(
        "INSERT INTO conversations(module,title,messages,kind,skill,template_id,category_id,native_session_id,draft_prompt,skill_version_id) VALUES ('agent',?,'[]',?,?,?,?,?,?,?)",
        (title, kind, skill, template_id, category_id, native_session_id, draft_prompt, skill_version_id),
    )


def link_papers(db: sqlite3.Connection, sid: int, ids: list[int]) -> None:
    db.executemany(
        'INSERT INTO conversation_papers(conversation_id,paper_id) VALUES (?,?)',
        [(sid, p) for p in ids],
    )


def link_paper(db: sqlite3.Connection, sid: int, pid: int) -> None:
    db.execute('INSERT OR IGNORE INTO conversation_papers(conversation_id,paper_id) VALUES (?,?)', (sid, pid))


def session_papers(db: sqlite3.Connection, sid: int):
    return db.execute(
        'SELECT p.id,p.title FROM papers p JOIN conversation_papers x ON x.paper_id=p.id WHERE x.conversation_id=?',
        (sid,),
    ).fetchall()


def update_session_field(db: sqlite3.Connection, sid: int, key: str, value) -> None:
    db.execute(f'UPDATE conversations SET {key}=? WHERE id=?', (value, sid))
