"""Business rules for task sessions, templates and session categories."""
from __future__ import annotations

import json
import sqlite3
import uuid

from ..agent.catalog import KINDS, SKILLS
from ..core.errors import ServiceError
from ..papers.service import paper_exists
from ..skills import repository as skills_repo, service as skills_service
from . import repository as repo
from .schemas import Name, SessionCreate, SessionPatch, TemplateCreate


def require_session(db: sqlite3.Connection, session_id: int):
    row = repo.find_session(db, session_id)
    if row is None:
        raise ServiceError(404, '会话不存在')
    return row


def session_view(db: sqlite3.Connection, row) -> dict:
    from ..agent import service as agent_service  # late import: agent.service imports this module

    out = {k: row[k] for k in ('id', 'title', 'kind', 'execution_mode', 'parent_session_id', 'entry_context', 'skill', 'skill_version_id', 'category_id', 'template_id', 'native_session_id', 'native_ready', 'archived', 'pinned', 'draft_prompt', 'created_at', 'updated_at')}
    binding=json.loads(row['runner_connection_json']) if row['runner_connection_json'] else None
    out['connection_binding']={k:binding[k] for k in ('mode','name','model','revision') if k in binding} if binding else None
    out['paper_ids'] = repo.paper_ids(db, row['id'])
    out['stale_paper_ids'] = [r[0] for r in db.execute('SELECT cp.paper_id FROM conversation_papers cp JOIN papers p ON p.id=cp.paper_id JOIN document_versions v ON v.id=p.default_version_id WHERE cp.conversation_id=? AND cp.file_version IS NOT NULL AND cp.file_version<>v.file_hash', (row['id'],))]
    out['run_count'] = agent_service.run_count(db, row['id'])
    last = agent_service.last_run_summary(db, row['id'])
    out['last_status'] = last['status'] if last else 'draft'
    out['preview'] = (last['answer'] or last['prompt'])[:160] if last else ''
    return out


def templates_view(db: sqlite3.Connection) -> dict:
    skills_service.ensure_builtin_skills(db)
    return {
        'templates': [dict(r) for r in repo.list_templates(db)],
        'kinds': KINDS,
        'skills': [
            {'id': r['id'], 'name': r['name']}
            for r in skills_repo.list_skills(db, status='enabled')
        ],
    }


def create_template(db: sqlite3.Connection, body: TemplateCreate) -> dict:
    dynamic_skill = skills_repo.find_skill(db, body.skill)
    if dynamic_skill is not None:
        if dynamic_skill['status'] != 'enabled':
            raise ServiceError(400, 'Skill 已停用，不能创建模板')
    elif body.skill not in SKILLS:
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
    from ..agent import service as agent_service

    run_match_ids = agent_service.conversation_ids_matching(db, q) if q else ()
    rows = repo.search_sessions(db, q=q, kind=kind, paper_id=paper_id, category_id=category_id, archived=archived, limit=limit, run_match_ids=run_match_ids)
    return {'sessions': [session_view(db, r) for r in rows]}


def create_session(db: sqlite3.Connection, body: SessionCreate) -> dict:
    skills_service.ensure_builtin_skills(db)
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
    selected=dict(template)
    surface=body.entry_context or ('compare' if template['skill']=='paper_compare' else 'review' if template['skill']=='paper_review' else 'reader_chat' if ids else 'research_chat')
    if body.entry_context and surface not in ('reader_chat','research_chat','review','compare'):
        raise ServiceError(422, '请使用专用任务入口')
    if body.skill_version_id and not body.skill_id:
        raise ServiceError(422, '版本需要指定技能')
    if body.skill_id:
        from ..skills import authoring
        if surface in ('reader_chat','review') and not ids:raise ServiceError(422,'该功能需要论文')
        if surface=='compare' and len(ids)<2:raise ServiceError(422,'比较需要至少两篇论文')
        if surface not in ('reader_chat','research_chat','review','compare'):raise ServiceError(422,'请使用专用任务入口')
        if surface not in authoring.placements(db,body.skill_id)['surfaces']:raise ServiceError(409,'所选技能未开放到此功能')
        try:p=authoring.compatible(db,body.skill_id,body.skill_version_id,surface)
        except ValueError as e:raise ServiceError(409,str(e)) from None
        selected.update(skill=body.skill_id,skill_version_id=p['version_id'])
    template=selected
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
            skill_version_id=template['skill_version_id'],
        )
        ident = cur.lastrowid
        db.execute('UPDATE conversations SET entry_context=? WHERE id=?',(surface,ident))
        repo.link_papers(db, ident, ids)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'session': session_view(db, require_session(db, ident)), 'starting_prompt': starting_prompt}


def link_paper(db: sqlite3.Connection, session_id: int, paper_id: int) -> None:
    repo.link_paper(db, session_id, paper_id)


def usage_summary(db: sqlite3.Connection, session_id: int) -> dict:
    """Sum only usage fields actually recorded in agent_runs.

    The totals are accounting records, not an estimate of current context-window
    occupancy; absent fields remain absent rather than being fabricated.
    """
    totals = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'runs_with_usage': 0, 'runs_with_input_tokens': 0, 'runs_with_output_tokens': 0, 'runs_with_total_tokens': 0}
    costs = []
    for row in db.execute('SELECT usage_json,cli_estimated_cost_usd FROM agent_runs WHERE conversation_id=?', (session_id,)):
        try:
            usage = json.loads(row['usage_json'] or '{}')
        except (TypeError, json.JSONDecodeError):
            usage = {}
        if not isinstance(usage, dict):
            usage = {}
        has_input = 'input_tokens' in usage
        has_output = 'output_tokens' in usage
        has_total = 'total_tokens' in usage
        if has_input or has_output or has_total:
            totals['runs_with_usage'] += 1
        if has_input:
            totals['runs_with_input_tokens'] += 1
            totals['input_tokens'] += int(usage.get('input_tokens') or 0)
        if has_output:
            totals['runs_with_output_tokens'] += 1
            totals['output_tokens'] += int(usage.get('output_tokens') or 0)
        if has_total or (has_input and has_output):
            totals['runs_with_total_tokens'] += 1
            totals['total_tokens'] += int(usage.get('total_tokens') or ((usage.get('input_tokens') or 0) + (usage.get('output_tokens') or 0)))
        if row['cli_estimated_cost_usd'] is not None:
            costs.append(float(row['cli_estimated_cost_usd']))
    totals['cli_estimated_cost_usd'] = sum(costs) if costs else None
    return totals


def session_detail(db: sqlite3.Connection, session_id: int) -> dict:
    row = require_session(db, session_id)
    return {'session': session_view(db, row), 'papers': [dict(r) for r in repo.session_papers(db, session_id)], 'usage': usage_summary(db, session_id)}


def session_runs(db: sqlite3.Connection, session_id: int, before: int | None = None, limit: int = 50) -> dict:
    from ..agent import service as agent_service

    require_session(db, session_id)
    rows = agent_service.session_runs(db, session_id, before, limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    return {'runs': [agent_service.view(r) for r in reversed(rows)], 'has_more': more, 'next_before': rows[-1]['sequence'] if rows else None}


def update_session(db: sqlite3.Connection, session_id: int, body: SessionPatch) -> dict:
    from ..agent import service as agent_service

    require_session(db, session_id)
    if body.archived and agent_service.has_active_run(db, session_id):
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
