"""SQLite access for the unified dynamic skill registry."""
from __future__ import annotations

import sqlite3


def list_skills(db, *, q: str = '', status: str | None = None, category_id: int | None = None,
                source: str | None = None, limit: int = 100, offset: int = 0):
    sql = 'SELECT * FROM skills WHERE 1=1'
    args: list = []
    if q:
        sql += ' AND (instr(lower(name),lower(?))>0 OR instr(lower(description),lower(?))>0)'
        args += [q, q]
    if status:
        sql += ' AND status=?'
        args.append(status)
    if source:
        sql += ' AND source=?'
        args.append(source)
    if category_id is not None:
        sql += ' AND id IN (SELECT skill_id FROM skill_category_items WHERE category_id=?)'
        args.append(category_id)
    return db.execute(
        sql + ' ORDER BY source DESC, revision DESC, rowid LIMIT ? OFFSET ?',
        args + [limit, offset],
    ).fetchall()


def count_skills(db) -> int:
    return db.execute('SELECT count(*) FROM skills').fetchone()[0]


def find_skill(db, skill_id: str):
    return db.execute('SELECT * FROM skills WHERE id=?', (skill_id,)).fetchone()


def insert_skill(db, *, ident, name, description, source, status='disabled'):
    db.execute(
        'INSERT INTO skills(id,name,description,source,status) VALUES (?,?,?,?,?)',
        (ident, name, description, source, status),
    )


def update_skill_meta(db, skill_id: str, *, name=None, description=None):
    changed = False
    if name is not None:
        db.execute('UPDATE skills SET name=?, revision=revision+1 WHERE id=?', (name, skill_id))
        changed = True
    if description is not None:
        db.execute('UPDATE skills SET description=?, revision=revision+1 WHERE id=?', (description, skill_id))
        changed = True
    if changed:
        bump_revision(db)


def set_skill_status(db, skill_id: str, status: str):
    db.execute('UPDATE skills SET status=?, revision=revision+1 WHERE id=?', (status, skill_id))
    bump_revision(db)


def set_default_version(db, skill_id: str, version_id: int):
    db.execute('UPDATE skills SET default_version_id=?, revision=revision+1 WHERE id=?', (version_id, skill_id))
    bump_revision(db)


def latest_revision(db) -> int:
    row = db.execute('SELECT revision FROM skill_registry_state WHERE singleton_id=1').fetchone()
    return row['revision'] if row else 0


def bump_revision(db) -> None:
    db.execute('UPDATE skill_registry_state SET revision=revision+1 WHERE singleton_id=1')


def insert_version(db, *, skill_id, version, content_hash, storage_key, entry, manifest_json,
                   validation_status='validated'):
    cur = db.execute(
        'INSERT INTO skill_versions(skill_id,version,content_hash,storage_key,entry,manifest_json,validation_status)'
        ' VALUES (?,?,?,?,?,?,?)',
        (skill_id, version, content_hash, storage_key, entry, manifest_json, validation_status),
    )
    bump_revision(db)
    return cur.lastrowid


def find_version(db, version_id: int):
    return db.execute('SELECT * FROM skill_versions WHERE id=?', (version_id,)).fetchone()


def versions_for_skill(db, skill_id: str):
    return db.execute('SELECT * FROM skill_versions WHERE skill_id=? ORDER BY id DESC', (skill_id,)).fetchall()


def version_usage_counts(db, version_id: int) -> dict[str, int]:
    row = db.execute(
        '''
        SELECT
            (SELECT count(*) FROM conversations WHERE skill_version_id=?) AS sessions,
            (SELECT count(*) FROM agent_runs WHERE skill_version_id=?) AS runs,
            (SELECT count(*) FROM task_templates WHERE skill_version_id=?) AS templates
        ''',
        (version_id, version_id, version_id),
    ).fetchone()
    return {'sessions': row['sessions'], 'runs': row['runs'], 'templates': row['templates']}


def find_version_by_hash(db, content_hash: str):
    return db.execute('SELECT * FROM skill_versions WHERE content_hash=?', (content_hash,)).fetchone()


def find_version_by_skill_version(db, skill_id: str, version: str):
    return db.execute(
        'SELECT * FROM skill_versions WHERE skill_id=? AND version=?',
        (skill_id, version),
    ).fetchone()


def default_version(db, skill_id: str):
    skill = find_skill(db, skill_id)
    if not skill or not skill['default_version_id']:
        return None
    return find_version(db, skill['default_version_id'])


def list_categories(db):
    return db.execute(
        'SELECT c.*,(SELECT count(*) FROM skill_category_items i WHERE i.category_id=c.id) AS count'
        ' FROM skill_categories c ORDER BY c.sort_order,c.rowid'
    ).fetchall()


def find_category_by_name(db, name: str):
    return db.execute('SELECT * FROM skill_categories WHERE lower(name)=lower(?)', (name,)).fetchone()


def insert_category(db, name: str, sort_order: int = 0):
    cur = db.execute('INSERT INTO skill_categories(name,sort_order) VALUES (?,?)', (name, sort_order))
    return cur.lastrowid


def rename_category(db, category_id: int, name: str):
    db.execute('UPDATE skill_categories SET name=? WHERE id=?', (category_id, name))


def delete_category(db, category_id: int):
    db.execute('DELETE FROM skill_category_items WHERE category_id=?', (category_id,))
    db.execute('DELETE FROM skill_categories WHERE id=?', (category_id,))


def set_categories(db, skill_id: str, category_ids: list[int]):
    db.execute('DELETE FROM skill_category_items WHERE skill_id=?', (skill_id,))
    db.executemany(
        'INSERT OR IGNORE INTO skill_category_items(skill_id,category_id) VALUES (?,?)',
        [(skill_id, c) for c in category_ids],
    )


def skill_category_ids(db, skill_id: str) -> list[int]:
    return [r[0] for r in db.execute('SELECT category_id FROM skill_category_items WHERE skill_id=?', (skill_id,))]


def insert_import(db, *, ident, status, filename='', report_json='{}', candidate_json='{}',
                  archive_hash='', request_key=''):
    db.execute(
        'INSERT INTO skill_imports(id,filename,archive_hash,request_key,status,report_json,candidate_json)'
        ' VALUES (?,?,?,?,?,?,?)',
        (ident, filename, archive_hash, request_key, status, report_json, candidate_json),
    )


def insert_dynamic_template(
    db, *, ident, name, description, kind, skill, prompt,
    skill_version_id, source_template_key,
):
    db.execute(
        'INSERT INTO task_templates('
        'id,name,description,kind,skill,prompt,builtin,skill_version_id,source_template_key'
        ') VALUES (?,?,?,?,?,?,0,?,?)',
        (ident, name, description, kind, skill, prompt, skill_version_id, source_template_key),
    )


def update_import(db, ident: str, **fields):
    if not fields:
        return
    keys = ','.join(f'{k}=?' for k in fields)
    db.execute(f'UPDATE skill_imports SET {keys} WHERE id=?', (*fields.values(), ident))


def find_import(db, ident: str):
    return db.execute('SELECT * FROM skill_imports WHERE id=?', (ident,)).fetchone()


def import_by_hash(db, archive_hash: str):
    return db.execute(
        "SELECT * FROM skill_imports WHERE archive_hash=? AND status IN ('awaiting_config','installed')",
        (archive_hash,),
    ).fetchone()


def audit(db, *, skill_id=None, version_id=None, action: str, detail_json='{}'):
    db.execute(
        'INSERT INTO skill_audit(skill_id,version_id,action,detail_json) VALUES (?,?,?,?)',
        (skill_id, version_id, action, detail_json),
    )


def audits_for_skill(db, skill_id: str, limit: int = 100, offset: int = 0):
    return db.execute(
        'SELECT * FROM skill_audit WHERE skill_id=? ORDER BY id DESC LIMIT ? OFFSET ?',
        (skill_id, limit, offset),
    ).fetchall()


def get_pref(db, key: str):
    return db.execute('SELECT * FROM user_preferences WHERE key=?', (key,)).fetchone()


def set_pref(db, key: str, value_json: str, expected_revision: int | None):
    row = get_pref(db, key)
    if row is None:
        db.execute('INSERT INTO user_preferences(key,value_json) VALUES (?,?)', (key, value_json))
        return
    if expected_revision is not None and row['revision'] != expected_revision:
        raise sqlite3.IntegrityError('revision')
    db.execute(
        'UPDATE user_preferences SET value_json=?, revision=revision+1, updated_at=CURRENT_TIMESTAMP WHERE key=?',
        (value_json, key),
    )
