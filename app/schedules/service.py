"""Business rules for interval research tasks and their dispatch loop."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone


from ..core.errors import ServiceError
from ..sessions.service import require_session
from . import repository as repo
from .schemas import Enable, Schedule


def next_time(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')


def schedules_view(db) -> dict:
    return {'schedules': [dict(r) for r in repo.list_schedules(db)]}


def create_schedule(db, body: Schedule) -> dict:
    session = require_session(db, body.conversation_id)
    if not body.title.strip() or not body.prompt.strip():
        raise ServiceError(400, '任务名称和要求不能为空')
    if session['archived']:
        raise ServiceError(400, '请选择未归档的会话')
    if session['skill'] == 'paper_import':
        raise ServiceError(400, '导入任务不能定时重复执行')
    if session['skill'] in ('paper_read', 'paper_review', 'paper_compare'):
        papers = repo.session_pdfs(db, body.conversation_id)
        if not papers or any(not p['pdf_path'] for p in papers):
            raise ServiceError(400, '请先为关联论文补充 PDF 全文')
    cur = repo.insert_schedule(db, body.title.strip(), body.conversation_id, body.prompt, body.interval_hours, body.enabled, next_time(body.interval_hours))
    db.commit()
    return dict(repo.find_schedule(db, cur.lastrowid))


def enable_schedule(db, ident: int, body: Enable) -> dict:
    r = repo.find_schedule(db, ident)
    if r is None:
        raise ServiceError(404, '定时任务不存在')
    repo.set_enabled(db, ident, body.enabled, next_time(r['interval_hours']))
    db.commit()
    return {'saved': True}


async def fire_schedule(ident: int, db, state, slot: str | None = None) -> dict:
    from ..agent.schemas import RunCreate
    from ..agent.service import create_run

    r = repo.find_schedule(db, ident)
    if r is None:
        raise ServiceError(404, '定时任务不存在')
    if r['kind'] == 'frontier':
        from ..frontier.service import trigger
        result = await trigger(db, state, r['frontier_topic_id'], f"schedule:{ident}:{slot}" if slot else "manual:"+uuid.uuid4().hex)
        db.execute('UPDATE research_schedules SET last_error=NULL WHERE id=?',(ident,))
        repo.set_last_run(db, ident, result['agent_run_id'], next_time(r['interval_hours']))
        db.commit()
        return result
    run = await create_run(RunCreate(conversation_id=r['conversation_id'], prompt=r['prompt']), state)
    db.execute('UPDATE research_schedules SET last_error=NULL WHERE id=?',(ident,))
    repo.set_last_run(db, ident, run['id'], next_time(r['interval_hours']))
    db.commit()
    return run


async def schedule_loop(app):
    while True:
        await asyncio.sleep(60)
        db = app.state.db
        from ..frontier.service import reconcile
        reconcile(db)
        for row in repo.due_schedules(db):
            # Advance before dispatch: a restart must never replay billed work.
            repo.advance_next(db, row['id'], next_time(row['interval_hours']))
            db.commit()
            # Busy/full queues are normal refusals: skip, never hammer retries.
            try:
                await fire_schedule(row['id'], db, app.state, slot=row['next_at'])
            except ServiceError as exc:
                db.execute('UPDATE research_schedules SET last_error=? WHERE id=?',(str(exc.detail)[:300],row['id']))
                db.commit()
