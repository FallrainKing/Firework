"""Persisted agent runs: idempotent creation and single-flight execution."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid

import httpx

from ..core.db import get_conn
from ..core.workspaces import workspace_context
from ..core.errors import ServiceError
from ..reader.service import validate_context
from ..sessions.service import require_session
from ..skills import repository as skills_repository
from ..skills import service as skills_service
from . import repository as repo, runner_client
from .catalog import SKILLS as CATALOG, TEMPLATES
from .schemas import RunCreate
from ..runner_config import budgets,connections
from . import diagnostics
from .protocol import RUNNER_PROTOCOL_VERSION

logger = logging.getLogger(__name__)
SKILLS = {k: v['name'] for k, v in CATALOG.items()}


def view(row) -> dict:
    result = dict(row)
    for key in ('usage', 'tool_calls', 'metadata'):
        result[key] = json.loads(result.pop(key + '_json'))
    result['contexts'] = json.loads(result.pop('context_json', '[]'))
    result['attachment_ids'] = json.loads(result.pop('attachment_ids_json', '[]'))
    result['progress'] = json.loads(result.pop('progress_json', '{}') or '{}')
    result['diagnostics'] = diagnostics.view(row)
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
    # This MVP deployment runs one web worker. Interrupted runs are marked
    # explicitly; never auto-retry a possibly billed model request.
    app.state.interrupted_run_ids = [r['id'] for r in db.execute("SELECT id FROM agent_runs WHERE status IN ('queued','running')").fetchall()]
    repo.fail_interrupted_runs(db)
    repo.fail_orphan_imports(db)
    db.commit()


async def _cancel_runner_jobs(db, run_ids):
    """Best-effort: stop runner jobs the app no longer owns (shutdown/restart).

    Prevents orphaned billing and concurrent CLI runs on one native session.
    """
    if not run_ids:
        return
    try:
        async with runner_client.client() as c:
            for rid in run_ids:
                with contextlib.suppress(httpx.HTTPError):
                    await c.post(f'/runs/{rid}/cancel', timeout=3)
    except httpx.HTTPError:
        pass


async def cancel_orphaned_runner_jobs(state):
    await _cancel_runner_jobs(state.db, getattr(state, 'interrupted_run_ids', []))


async def close_agent_state(app):
    db = app.state.db
    active = [r['id'] for r in db.execute("SELECT id FROM agent_runs WHERE status IN ('queued','running')").fetchall()]
    await _cancel_runner_jobs(db, active)
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
    registry = skills_service.registry_view(db)
    return {
        'runner': runner,
        'required_runner_protocol': RUNNER_PROTOCOL_VERSION,
        'runner_protocol_compatible': runner.get('status') == 'ok' and runner.get('protocol_version') == RUNNER_PROTOCOL_VERSION,
        'runs': counts,
        'database': 'ok',
        'registry_revision': registry['registry_revision'],
        'skills': registry['skills'],
        'limits': {
            'concurrency': runner.get('concurrency', 2),
            'max_queued': 8,
            'skills': {k: {'max_turns': v['max_turns'], 'max_output_tokens': v['max_output_tokens'], 'timeout_s': v['timeout_s'], 'max_budget_usd': v['max_budget_usd']} for k, v in CATALOG.items()},
        },
        'cost_verified': False,
    }


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


def run_count(db, sid: int) -> int:
    return repo.run_count(db, sid)


def last_run_summary(db, sid: int):
    return repo.last_run(db, sid)


def has_active_run(db, sid: int) -> bool:
    return bool(repo.has_active_run(db, sid))


def session_runs(db, sid: int, before: int | None, limit: int):
    return repo.session_runs(db, sid, before, limit)


def conversation_ids_matching(db, q: str) -> list[int]:
    return repo.conversation_ids_matching(db, q)


def runs_by_ids(db, ids) -> dict:
    return repo.runs_by_ids(db, ids)


def search_library(db, q: str = '') -> dict:
    # Management lookup only. Agent performs research searches via MCP.
    return {'papers': [dict(row) for row in repo.search_papers(db, q)]}


async def create_run(body: RunCreate, state) -> dict:
    prompt = body.prompt.strip()
    if not prompt:
        raise ServiceError(400, 'Message must not be empty')
    db = state.db
    skills_service.ensure_builtin_skills(db)
    registry = skills_service.registry_view(db)
    available = {s['id'] for s in registry['skills'] if s['status'] == 'enabled'}
    if body.skill is not None and body.skill not in available:
        raise ServiceError(400, 'Unknown skill')
    prior = repo.find_run_by_key(db, body.request_key)
    if prior:
        try:
            prior_contexts = [validate_context(state.settings, db, c.model_dump(), prior['conversation_id']) for c in body.contexts]
        except ValueError as e:
            raise ServiceError(409, str(e)) from e
        if (json.loads(prior['attachment_ids_json']) != body.attachment_ids
                or json.loads(prior['context_json']) != prior_contexts
                or prior['purpose'] != body.purpose
                or json.loads(prior['execution_policy_json'] or '{}').get('connection_selection') != (body.connection.model_dump() if body.connection else None)
                or json.loads(prior['execution_policy_json'] or '{}').get('budget_selection') != (body.budget.model_dump() if body.budget else None)
                or prior['prompt'] != prompt
                or (body.skill is not None and prior['skill'] != body.skill)
                or (body.conversation_id is not None and prior['conversation_id'] != body.conversation_id)):
            raise ServiceError(409, 'Request key already used for different input')
        return view(prior)
    if repo.count_active_runs(db) >= 8:
        raise ServiceError(429, 'Queue full; please wait')
    conv_id = body.conversation_id
    skill = body.skill or 'chat'
    if conv_id is not None:
        session = require_session(db, conv_id)
        from ..documents.service import guard_session
        guard_session(db, state.settings, state, conv_id)
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
            raise ServiceError(409, str(e)) from e

    session_version_id = None
    if conv_id is not None:
        session = require_session(db, conv_id)
        session_version_id = session['skill_version_id']
    try:
        policy = skills_service.execution_policy(db, skill, session_version_id)
    except ValueError as exc:
        raise ServiceError(409, str(exc)) from exc
    policy = budgets.resolve(db, policy, body.budget)
    binding = session['runner_connection_json'] if conv_id is not None else None
    if conv_id is not None and not binding and (session['native_ready'] or db.execute('SELECT 1 FROM agent_runs WHERE conversation_id=? LIMIT 1',(conv_id,)).fetchone()):
        binding = '{"mode":"legacy"}'
    connection_snapshot = connections.snapshot(db,state.settings,body.connection,binding)
    if body.attachment_ids and connection_snapshot.get('mode')=='custom' and connection_snapshot.get('vision')!='declared_yes':
        raise ServiceError(422,'当前连接尚未声明支持图片，请新建会话并选择视觉模型')
    if connection_snapshot.get('mode')=='custom' and policy['max_output_tokens']>connection_snapshot['context_window']:
        raise ServiceError(422,'输出额度超过模型声明的上下文容量')
    policy['connection_snapshot']=connection_snapshot
    policy['connection_selection']=body.connection.model_dump() if body.connection else None
    if conv_id is not None and session_version_id is None:
        repo.set_conversation_skill_version(db, conv_id, policy['version_id'])
        db.commit()

    # All writes happen without awaits; one transaction owns conversation+run.
    try:
        if conv_id is None:
            cursor = repo.insert_conversation(
                db,
                prompt[:80],
                skill,
                'discovery' if skill.startswith('search_') else 'chat',
                str(uuid.uuid4()),
                policy['version_id'],
            )
            conv_id = cursor.lastrowid
        run_id = uuid.uuid4().hex
        repo.insert_run(
            db,
            run_id,
            body.request_key,
            conv_id,
            skill,
            prompt,
            json.dumps(contexts, ensure_ascii=False),
            body.purpose,
            json.dumps(body.attachment_ids),
            policy['version_id'],
            policy['skill_hash'],
            json.dumps(policy, ensure_ascii=False),
            policy['version'],
        )
        db.execute('UPDATE conversations SET runner_connection_json=? WHERE id=? AND runner_connection_json IS NULL',(json.dumps(connection_snapshot,ensure_ascii=False),conv_id))
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


async def cancel_run(db, run_id: str, state) -> dict:
    row = repo.find_run(db, run_id)
    if row is None:
        raise ServiceError(404, 'Task not found')
    if row['status'] in ('succeeded', 'failed', 'cancelled'):
        raise ServiceError(409, '任务已结束')
    try:
        async with runner_client.client() as c:
            response = await c.post(f'/runs/{run_id}/cancel', timeout=10)
            if response.status_code != 404:
                response.raise_for_status()
    except httpx.HTTPError:
        raise ServiceError(503, 'Runner 离线，无法取消')
    repo.cancel_run(db, run_id)
    repo.fail_imports_for_run(db, run_id, '已取消')
    db.commit()
    return view(repo.find_run(db, run_id))

def run_snapshot(db, run_id: str):
    row = repo.find_run(db, run_id)
    if row is None:
        return None
    return {'status': row['status'], 'progress': json.loads(row['progress_json'] or '{}')}


async def execute_run(run_id: str, state):
    """Submit a runner job and consume its SSE progress until terminal.

    Concurrency is gated by the Runner (queue + semaphore), not here. A broken
    stream marks the run failed; a possibly billed request is never replayed.
    """
    db = get_conn(state.settings)
    workspace_token=workspace_context.set(getattr(state.settings,'workspace_key','legacy'))
    try:
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
        # Cancel may have landed while this task was starting: never submit a
        # run the user already cancelled (it would be billed and discarded).
        if repo.find_run(db, run_id)['status'] not in ('queued', 'running'):
            return
        try:
            async with runner_client.client() as c:
                connection_snap=json.loads(row['execution_policy_json'] or '{}').get('connection_snapshot')
                connection_secret=connections.materialize(db,state.settings,connection_snap)
                if json.loads(row['execution_policy_json'] or '{}').get('budget_snapshot') or (connection_snap and connection_snap.get('mode')=='custom'):
                    health = await c.get('/health', timeout=5)
                    health.raise_for_status()
                    if health.json().get('protocol_version') != RUNNER_PROTOCOL_VERSION:
                        raise ValueError('runner_protocol_mismatch')
                sub = await c.post('/runs', json={'run_id': run_id, 'skill': row['skill'], 'prompt': row['prompt'], 'history': history if not session['native_ready'] else [], 'session_id': session['native_session_id'], 'native_ready': bool(session['native_ready']), 'paper_ids': paper_ids, 'contexts': json.loads(row['context_json']), 'attachment_ids': json.loads(row['attachment_ids_json']), 'import_request_id': import_row['id'] if import_row else None, 'skill_version_id': row['skill_version_id'], 'skill_hash': row['skill_hash'], 'budget_policy': json.loads(row['execution_policy_json'] or '{}').get('budget_snapshot'), 'connection_snapshot':({k:v for k,v in connection_snap.items() if k!='mode'} if connection_snap and connection_snap.get('mode')=='custom' else None), 'connection_secret':connection_secret})
                sub.raise_for_status()
                if repo.find_run(db, run_id)['status'] not in ('queued', 'running'):
                    with contextlib.suppress(httpx.HTTPError):
                        await c.post(f'/runs/{run_id}/cancel', timeout=5)
                    return
                result = None
                last_write = 0.0
                async with c.stream('GET', f'/runs/{run_id}/events', timeout=httpx.Timeout(10.0, read=None)) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith('data: '):
                            continue
                        frame = json.loads(line[6:])
                        if frame.get('type') == 'progress':
                            event = frame.get('event') or {}
                            now = time.monotonic()
                            if event.get('tools') or now - last_write >= 1.0:
                                repo.update_progress(db, run_id, json.dumps(event, ensure_ascii=False))
                                db.commit()
                                last_write = now
                        elif frame.get('type') == 'result':
                            result = frame.get('result') or {}
                            break
                if result is None:
                    got = await c.get(f'/runs/{run_id}')
                    got.raise_for_status()
                    result = got.json().get('result')
                if not result or result.get('status') not in ('succeeded', 'failed', 'cancelled'):
                    raise ValueError('Invalid runner status')
        except ServiceError as exc:
            result={'status':'failed','error':exc.detail,'metadata':{'subtype':'connection_unavailable'}}
        except (httpx.HTTPError, ValueError) as exc:
            result = {'status': 'failed', 'error': ('Runner 版本不支持当前额度配置；本轮没有调用模型，请升级运行服务。' if str(exc)=='runner_protocol_mismatch' else 'Agent connection failed or timed out; retry manually. No automatic retry was made.')}
            if str(exc)=='runner_protocol_mismatch': result['metadata']={'subtype':'runner_protocol_mismatch'}
        repo.finish_run(db, run_id, result['status'], str(result.get('answer') or ''), result.get('model'), json.dumps(result.get('usage') or {}), json.dumps(result.get('tool_calls') or [], ensure_ascii=False), json.dumps(result.get('metadata') or {}), result.get('cli_estimated_cost_usd'), result.get('error'))
        if result['status'] == 'cancelled':
            repo.fail_imports_for_run(db, run_id, str(result.get('error') or '已取消'))
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
        workspace_context.reset(workspace_token)


async def validate_skill_run(skill_id: str, body, state) -> dict:
    """Create an explicit, minimal real run for an enabled dynamic skill.

    This endpoint intentionally does not fake validation: the caller sees that a
    model invocation will be submitted, and no upload/check/install path calls
    it automatically. The test suite mocks ``create_run`` at this boundary.
    """
    db = state.db
    skills_service.ensure_builtin_skills(db)
    skill = skills_repository.find_skill(db, skill_id)
    if skill is None:
        raise ServiceError(404, 'Skill not found')
    if skill['status'] != 'enabled':
        raise ServiceError(409, 'Skill must be enabled before validation')

    prompt = body.prompt.strip()
    request_key = body.request_key
    prior = repo.find_run_by_key(db, request_key)
    run = await create_run(RunCreate(
        prompt=prompt,
        skill=skill_id,
        purpose='skill-validation',
        request_key=request_key,
    ), state)
    if prior is None:
        skills_service.record_validate_run(
            db,
            skill_id=skill_id,
            version_id=run.get('skill_version_id'),
            run_id=run['id'],
        )
    return {
        'skill_id': skill_id,
        'version_id': run.get('skill_version_id'),
        'run_id': run['id'],
        'status': run['status'],
        'purpose': run['purpose'],
        'model_invocation': True,
    }
