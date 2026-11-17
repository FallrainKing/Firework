"""Persisted agent runs: idempotent creation and single-flight execution."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

import httpx

from ..core.db import get_conn
from ..core.errors import ServiceError
from ..reader.pages import validate_context
from ..sessions.service import require_session
from . import repository as repo, runner_client
from .catalog import SKILLS as CATALOG, TEMPLATES
from .schemas import RunCreate

logger = logging.getLogger(__name__)
SKILLS = {k: v['name'] for k, v in CATALOG.items()}


def view(row) -> dict:
    result = dict(row)
    for key in ('usage', 'tool_calls', 'metadata'):
        result[key] = json.loads(result.pop(key + '_json'))
    result['contexts'] = json.loads(result.pop('context_json', '[]'))
    result['attachment_ids'] = json.loads(result.pop('attachment_ids_json', '[]'))
    result['cost_verified'] = False
    return result


def init_agent_state(app):
    db = app.state.db
    repo.seed_templates(db, TEMPLATES)
    for row in repo.conversations_missing_native_id(db):
        repo.set_native_session(db, row['id'], str(uuid.uuid4()))
    repo.fail_orphan_imports(db)
    db.commit()
    app.state.agent_jobs = set()
    app.state.agent_semaphore = asyncio.Semaphore(1)
    # This MVP deployment runs one web worker. Interrupted runs are marked
    # explicitly; never auto-retry a possibly billed model request.
    repo.fail_interrupted_runs(db)
    repo.fail_orphan_imports(db)
    db.commit()


async def close_agent_state(app):
    jobs = list(app.state.agent_jobs)
    for job in jobs:
        job.cancel()
    if jobs:
        await asyncio.gather(*jobs, return_exceptions=True)


async def status_view(db) -> dict:
    counts = repo.run_status_counts(db)
    try:
        async with runner_client.client() as c:
            response = await c.get('/health', timeout=3)
            response.raise_for_status()
            runner = response.json()
    except (httpx.HTTPError, ValueError):
        runner = {'status': 'offline', 'skills': []}
    return {'runner': runner, 'runs': counts, 'database': 'ok', 'limits': {'concurrency': 1, 'max_queued': 8, 'max_output_tokens_per_turn': 1024, 'max_tool_calls': 4, 'max_tool_calls_search': 2, 'max_turns': 6, 'timeout_seconds': 120, 'cost_verified': False}}


def list_runs(db, conversation_id: int | None = None, q: str = '') -> dict:
    return {'runs': [view(row) for row in repo.list_runs(db, conversation_id, q)]}


def get_run(db, run_id: str) -> dict:
    row = repo.find_run(db, run_id)
    if row is None:
        raise ServiceError(404, 'Task not found')
    return view(row)


def run_row(db, run_id: str):
    """Raw run row for cross-domain binding checks (imports)."""
    return repo.find_run(db, run_id)


def search_library(db, q: str = '') -> dict:
    # Management lookup only. Agent performs research searches via MCP.
    return {'papers': [dict(row) for row in repo.search_papers(db, q)]}


async def create_run(body: RunCreate, state) -> dict:
    prompt = body.prompt.strip()
    if not prompt:
        raise ServiceError(400, 'Message must not be empty')
    if body.skill is not None and body.skill not in SKILLS:
        raise ServiceError(400, 'Unknown skill')
    db = state.db
    prior = repo.find_run_by_key(db, body.request_key)
    if prior:
        try:
            prior_contexts = [validate_context(state.settings, db, c.model_dump(), prior['conversation_id']) for c in body.contexts]
        except ValueError as e:
            raise ServiceError(409, str(e))
        if json.loads(prior['attachment_ids_json']) != body.attachment_ids or json.loads(prior['context_json']) != prior_contexts or prior['purpose'] != body.purpose or prior['prompt'] != prompt or (body.skill is not None and prior['skill'] != body.skill) or (body.conversation_id is not None and prior['conversation_id'] != body.conversation_id):
            raise ServiceError(409, 'Request key already used for different input')
        return view(prior)
    if repo.count_active_runs(db) >= 8:
        raise ServiceError(429, 'Queue full; please wait')
    conv_id = body.conversation_id
    skill = body.skill or 'chat'
    if conv_id is not None:
        session = require_session(db, conv_id)
        if session['archived']:
            raise ServiceError(409, '请先取消归档，再继续会话')
        if body.skill is not None and body.skill != session['skill']:
            raise ServiceError(409, '会话任务类型已固定；不同任务请创建新会话')
        skill = session['skill']
        if repo.has_active_run(db, conv_id):
            raise ServiceError(409, 'This conversation already has an active task')
    elif skill in ('paper_read', 'paper_review', 'paper_compare'):
        raise ServiceError(400, '请先通过任务模板创建关联论文的会话')
    if body.attachment_ids:
        from ..workbench.service import image_rows

        if conv_id is None:
            raise ServiceError(400, '图片需要关联论文会话')
        for image in image_rows(db, body.attachment_ids, conv_id):
            if not repo.paper_linked_to_conversation(db, conv_id, image['paper_id']):
                raise ServiceError(400, '图片所属论文未关联当前会话')
    contexts = []
    if body.contexts:
        if conv_id is None:
            raise ServiceError(400, '请先建立关联论文的会话')
        try:
            contexts = [validate_context(state.settings, db, c.model_dump(), conv_id) for c in body.contexts]
        except ValueError as e:
            raise ServiceError(409, str(e))
    # All writes happen without awaits; one transaction owns conversation+run.
    try:
        if conv_id is None:
            cursor = repo.insert_conversation(db, prompt[:80], skill, 'discovery' if skill.startswith('search_') else 'chat', str(uuid.uuid4()))
            conv_id = cursor.lastrowid
        run_id = uuid.uuid4().hex
        repo.insert_run(db, run_id, body.request_key, conv_id, skill, prompt, json.dumps(contexts, ensure_ascii=False), body.purpose, json.dumps(body.attachment_ids))
        repo.clear_draft(db, conv_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    task = asyncio.create_task(execute_run(run_id, state))
    state.agent_jobs.add(task)

    def finished(job):
        state.agent_jobs.discard(job)
        if not job.cancelled() and job.exception():
            logger.error('agent task crashed: %s', type(job.exception()).__name__)

    task.add_done_callback(finished)
    return view(repo.find_run(db, run_id))


async def execute_run(run_id: str, state):
    db = get_conn(state.settings)
    try:
        async with state.agent_semaphore:
            row = repo.find_run(db, run_id)
            session = require_session(db, row['conversation_id'])
            if not session['native_session_id']:
                repo.set_native_session(db, session['id'], str(uuid.uuid4()))
                db.commit()
                session = require_session(db, session['id'])
            paper_ids = repo.conversation_paper_ids(db, session['id'])
            past = repo.past_successful_runs(db, row['conversation_id'], run_id)
            import_row = repo.find_import_request(db, session['id'], run_id)
            history = []
            for entry in reversed(past):
                history.extend([{'role': 'user', 'content': entry['prompt']}, {'role': 'assistant', 'content': entry['answer']}])
            repo.set_run_status(db, run_id, 'running')
            db.commit()
            try:
                async with runner_client.client() as c:
                    response = await c.post('/run', json={'run_id': run_id, 'skill': row['skill'], 'prompt': row['prompt'], 'history': history if not session['native_ready'] else [], 'session_id': session['native_session_id'], 'native_ready': bool(session['native_ready']), 'paper_ids': paper_ids, 'contexts': json.loads(row['context_json']), 'attachment_ids': json.loads(row['attachment_ids_json']), 'import_request_id': import_row['id'] if import_row else None})
                    response.raise_for_status()
                    result = response.json()
                if result.get('status') not in ('succeeded', 'failed'):
                    raise ValueError('Invalid runner status')
            except (httpx.HTTPError, ValueError):
                result = {'status': 'failed', 'error': 'Agent connection failed or timed out; retry manually. No automatic retry was made.'}
            repo.finish_run(db, run_id, result['status'], str(result.get('answer') or ''), result.get('model'), json.dumps(result.get('usage') or {}), json.dumps(result.get('tool_calls') or [], ensure_ascii=False), json.dumps(result.get('metadata') or {}), result.get('cli_estimated_cost_usd'), result.get('error'))
            if result.get('session_id') == session['native_session_id'] and result.get('native_ready'):
                repo.set_native_ready(db, session['id'])
            repo.touch_conversation(db, row['conversation_id'])
            db.commit()
    except Exception:
        logger.exception('Agent execution failed before result persistence')
        db.rollback()
        repo.fail_run_if_active(db, run_id, '会话执行异常，未自动重试')
        db.commit()
    except asyncio.CancelledError:
        db.rollback()
        repo.fail_run(db, run_id, 'Service stopped; retry manually')
        db.commit()
        raise
    finally:
        db.close()
