"""Business rules for task sessions, templates and session categories."""
from __future__ import annotations

import sqlite3
import uuid

from ..agent.catalog import KINDS, SKILLS
from ..core.errors import ServiceError
from ..papers.service import paper_exists
from . import repository as repo
from .schemas import Name, SessionCreate, SessionPatch, TemplateCreate


def require_session(db: sqlite3.Connection, session_id: int):
    row = repo.find_session(db, session_id)
    if row is None:
        raise ServiceError(404, '会话不存在')
    return row


def session_view(db: sqlite3.Connection, row) -> dict:
    out = {k: row[k] for k in ('id', 'title', 'kind', 'skill', 'category_id', 'template_id', 'native_session_id', 'native_ready', 'archived', 'pinned', 'draft_prompt', 'created_at', 'updated_at')}
    out['paper_ids'] = repo.paper_ids(db, row['id'])
    out['run_count'] = repo.run_count(db, row['id'])
    last = repo.last_run(db, row['id'])
    out['last_status'] = last['status'] if last else 'draft'
    out['preview'] = (last['answer'] or last['prompt'])[:160] if last else ''
    return out


def templates_view(db: sqlite3.Connection) -> dict:
    return {
        'templates': [dict(r) for r in repo.list_templates(db)],
        'kinds': KINDS,
        'skills': [{'id': k, 'name': v['name']} for k, v in SKILLS.items()],
    }


def create_template(db: sqlite3.Connection, body: TemplateCreate) -> dict:
    if body.skill not in SKILLS:
        raise ServiceError(400, '未知 Skill')
    if not body.name.strip():
        raise ServiceError(400, '模板名称不能为空')
    ident = 'custom_' + uuid.uuid4().hex
    repo.insert_template(db, ident, body.name.strip(), body.description, 'custom', body.skill, body.prompt)
    db.commit()
    return dict(repo.find_template(db, ident))


def categories_view(db: sqlite3.Connection) -> dict:
    return {'categories': [dict(r) for r in repo.list_categories(db)]}


def create_category(db: sqlite3.Connection, body: Name) -> dict:
    if not body.name.strip():
        raise ServiceError(400, '分类名称不能为空')
    try:
        cur = repo.insert_category(db, body.name.strip())
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise ServiceError(409, '分类名称已存在')
    return {'id': cur.lastrowid, 'name': body.name.strip()}


def list_sessions(db, *, q='', kind=None, paper_id=None, category_id=None, archived=False, limit=100) -> dict:
    rows = repo.search_sessions(db, q=q, kind=kind, paper_id=paper_id, category_id=category_id, archived=archived, limit=limit)
    return {'sessions': [session_view(db, r) for r in rows]}


def create_session(db: sqlite3.Connection, body: SessionCreate) -> dict:
    template = repo.find_template(db, body.template_id)
    if template is None:
        raise ServiceError(400, '模板不存在')
    if body.category_id is not None and not repo.category_exists(db, body.category_id):
        raise ServiceError(400, '分类不存在')
    ids = list(dict.fromkeys(body.paper_ids))
    if template['skill'] in ('paper_read', 'paper_review') and not ids:
        raise ServiceError(400, '请选择至少一篇论文')
    if template['skill'] == 'paper_compare' and len(ids) < 2:
        raise ServiceError(400, '对比会话至少选择两篇论文')
    for ident in ids:
        if not paper_exists(db, ident):
            raise ServiceError(400, '关联论文不存在')
    starting_prompt = body.starting_prompt if body.starting_prompt is not None else template['prompt']
    try:
        cur = repo.insert_session(
            db,
            title=body.title.strip() or template['name'],
            kind=template['kind'],
            skill=template['skill'],
            template_id=template['id'],
            category_id=body.category_id,
            native_session_id=str(uuid.uuid4()),
            draft_prompt=starting_prompt,
        )
        ident = cur.lastrowid
        repo.link_papers(db, ident, ids)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'session': session_view(db, require_session(db, ident)), 'starting_prompt': starting_prompt}


def session_detail(db: sqlite3.Connection, session_id: int) -> dict:
    row = require_session(db, session_id)
    return {'session': session_view(db, row), 'papers': [dict(r) for r in repo.session_papers(db, session_id)]}


def session_runs(db: sqlite3.Connection, session_id: int, before: int | None = None, limit: int = 50) -> dict:
    from ..agent.service import view

    require_session(db, session_id)
    rows = repo.session_runs(db, session_id, before, limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    return {'runs': [view(r) for r in reversed(rows)], 'has_more': more, 'next_before': rows[-1]['sequence'] if rows else None}


def update_session(db: sqlite3.Connection, session_id: int, body: SessionPatch) -> dict:
    require_session(db, session_id)
    if body.archived and repo.has_active_run(db, session_id):
        raise ServiceError(409, '执行中的会话暂不能归档')
    changes = body.model_dump(exclude_unset=True)
    if changes.get('title') is not None:
        changes['title'] = changes['title'].strip()
        if not changes['title']:
            raise ServiceError(400, '标题不能为空')
    if changes.get('category_id') is not None and not repo.category_exists(db, changes['category_id']):
        raise ServiceError(400, '分类不存在')
    for key, value in changes.items():
        if value is None and key != 'category_id':
            continue
        repo.update_session_field(db, session_id, key, value)
    db.commit()
    return session_view(db, require_session(db, session_id))
