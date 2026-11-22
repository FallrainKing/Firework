"""Transactional category lifecycle; source-owned Zotero paths remain immutable."""
import sqlite3
import uuid
from ..core.errors import ServiceError


def node(db, ident):
    row = db.execute('SELECT * FROM paper_collections WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ServiceError(404, '分类不存在')
    return row


def managed(db, ident):
    seen = set()
    while ident is not None and ident not in seen:
        seen.add(ident)
        row = node(db, ident)
        if row['parent_id'] is None:
            return row['name'].startswith('Zotero · ')
        ident = row['parent_id']
    return False


def writable(db, ident):
    if managed(db, ident):
        raise ServiceError(409, 'Zotero 来源分类由同步维护，请在 Zotero 修改；可另外建立个人分类')


def parent_allowed(db, ident):
    row = node(db, ident)
    if row['deleted_at'] is not None:
        raise ServiceError(409, '父分类已在回收站，请先恢复')
    writable(db, ident)


def revision_matches(row, expected):
    if row['revision'] != expected:
        raise ServiceError(409, '分类已被更新，请刷新后重试')


def patch(db, ident, body):
    try:
        db.execute('BEGIN IMMEDIATE')
        row = node(db, ident)
        if row['deleted_at'] is not None:
            raise ServiceError(409, '请先恢复分类')
        writable(db, ident)
        revision_matches(row, body.expected_revision)
        name = body.name.strip()
        if not name or name.startswith('Zotero · '):
            raise ServiceError(422, '分类名称不能为空，且不能使用保留的 Zotero 来源前缀')
        parent = body.parent_id
        if parent is not None:
            parent_allowed(db, parent)
            descendants = {r[0] for r in db.execute('WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT c.id FROM paper_collections c JOIN tree t ON c.parent_id=t.id) SELECT id FROM tree', (ident,))}
            if parent in descendants:
                raise ServiceError(409, '不能将分类移动到自身或子分类中')
        db.execute('UPDATE paper_collections SET name=?,parent_id=?,revision=revision+1 WHERE id=?', (name, parent, ident))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise ServiceError(409, '目标父分类下已有同名分类')
    except Exception:
        db.rollback()
        raise


def trash(db, ident, expected):
    try:
        db.execute('BEGIN IMMEDIATE')
        row = node(db, ident)
        writable(db, ident)
        revision_matches(row, expected)
        if row['deleted_at'] is not None:
            raise ServiceError(409, '分类已在回收站，请刷新')
        ids = [r[0] for r in db.execute('WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT c.id FROM paper_collections c JOIN tree t ON c.parent_id=t.id WHERE c.deleted_at IS NULL) SELECT id FROM tree', (ident,))]
        marks = ','.join('?' for _ in ids)
        if db.execute(f"SELECT 1 FROM import_requests WHERE collection_id IN ({marks}) AND status IN ('pending','running')", ids).fetchone():
            raise ServiceError(409, '分类仍有导入任务，请等待完成后再删除')
        db.execute(f'UPDATE paper_collections SET deleted_at=CURRENT_TIMESTAMP,deletion_group=?,revision=revision+1 WHERE id IN ({marks})', [uuid.uuid4().hex, *ids])
        db.commit()
    except Exception:
        db.rollback()
        raise


def restore(db, ident, expected):
    try:
        db.execute('BEGIN IMMEDIATE')
        row = node(db, ident)
        revision_matches(row, expected)
        if row['deleted_at'] is None:
            raise ServiceError(409, '分类已恢复，请刷新')
        group = row['deletion_group']
        # Only the batch root is restored, never a fragment of a deleted tree.
        if row['parent_id'] is not None:
            parent = node(db, row['parent_id'])
            if parent['deletion_group'] == group:
                raise ServiceError(409, '请从分类回收站恢复整个父分类')
            parent_allowed(db, row['parent_id'])
        writable(db, ident)
        db.execute('UPDATE paper_collections SET deleted_at=NULL,deletion_group=NULL,revision=revision+1 WHERE deletion_group=?', (group,))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise ServiceError(409, '原位置已有同名分类，请先重命名或移动现有分类后再恢复')
    except Exception:
        db.rollback()
        raise
