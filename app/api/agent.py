"""MVP management API: persist tasks and delegate all new processing to Claude."""
from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import uuid
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from ..db import get_conn

router = APIRouter(prefix='/api/agent', tags=['agent'])
logger = logging.getLogger(__name__)
SKILLS = {'chat': '科研对话', 'search_library': '搜索论文库', 'search_arxiv': '搜索 arXiv'}
SOCKET_DEFAULT = '/app/data/agent/runner.sock'

class RunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    skill: str = 'chat'
    conversation_id: int | None = None
    request_key: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=80)


def client():
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=os.getenv('AGENT_RUNNER_SOCKET', SOCKET_DEFAULT)), base_url='http://agent-runner', timeout=135.0)


def view(row) -> dict:
    result = dict(row)
    for key in ('usage', 'tool_calls', 'metadata'):
        result[key] = json.loads(result.pop(key + '_json'))
    result['cost_verified'] = False
    return result


def init_agent_state(app):
    app.state.agent_jobs = set()
    app.state.agent_semaphore = asyncio.Semaphore(1)
    # This MVP deployment runs one web worker. Interrupted runs are marked
    # explicitly; never auto-retry a possibly billed model request.
    app.state.db.execute("UPDATE agent_runs SET status='failed', error='Service restarted; retry manually to avoid duplicate usage', finished_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')")
    app.state.db.commit()

async def close_agent_state(app):
    jobs = list(app.state.agent_jobs)
    for job in jobs:
        job.cancel()
    if jobs:
        await asyncio.gather(*jobs, return_exceptions=True)

@router.get('/status')
async def status(request: Request):
    counts = dict(request.app.state.db.execute('SELECT status,count(*) FROM agent_runs GROUP BY status').fetchall())
    try:
        async with client() as c:
            response = await c.get('/health', timeout=3)
            response.raise_for_status()
            runner = response.json()
    except (httpx.HTTPError, ValueError):
        runner = {'status': 'offline', 'skills': []}
    return {'runner': runner, 'runs': counts, 'database': 'ok', 'limits': {'concurrency': 1, 'max_queued': 8, 'max_output_tokens_per_turn': 1024, 'max_tool_calls': 2, 'timeout_seconds': 120, 'cost_verified': False}}

@router.get('/runs')
async def list_runs(request: Request, conversation_id: int | None = None, q: str = Query('', max_length=200)):
    sql = 'SELECT * FROM agent_runs WHERE 1=1'
    args = []
    if conversation_id is not None:
        sql += ' AND conversation_id=?'; args.append(conversation_id)
    if q:
        sql += ' AND (instr(lower(prompt),lower(?))>0 OR instr(lower(answer),lower(?))>0)'; args.extend([q,q])
    rows = request.app.state.db.execute(sql + ' ORDER BY created_at DESC, rowid DESC LIMIT 50', args).fetchall()
    return {'runs': [view(row) for row in rows]}

@router.get('/runs/{run_id}')
async def get_run(run_id: str, request: Request):
    row = request.app.state.db.execute('SELECT * FROM agent_runs WHERE id=?', (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Task not found')
    return view(row)

@router.get('/library')
async def search_library(request: Request, q: str = Query('', max_length=200)):
    # Management lookup only. Agent performs research searches via MCP.
    rows = request.app.state.db.execute("SELECT id,title,authors,abstract,arxiv_id,status FROM papers WHERE instr(lower(coalesce(title,'')),lower(?))>0 OR instr(lower(coalesce(abstract,'')),lower(?))>0 ORDER BY id DESC LIMIT 50", (q,q)).fetchall()
    return {'papers': [dict(row) for row in rows]}

@router.post('/runs', status_code=202)
async def create_run(body: RunCreate, request: Request):
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, 'Message must not be empty')
    if body.skill not in SKILLS:
        raise HTTPException(400, 'Unknown skill')
    state = request.app.state
    db = state.db
    prior = db.execute('SELECT * FROM agent_runs WHERE request_key=?', (body.request_key,)).fetchone()
    if prior:
        if prior['prompt'] != prompt or prior['skill'] != body.skill or (body.conversation_id is not None and prior['conversation_id'] != body.conversation_id):
            raise HTTPException(409, 'Request key already used for different input')
        return view(prior)
    if db.execute("SELECT count(*) FROM agent_runs WHERE status IN ('queued','running')").fetchone()[0] >= 8:
        raise HTTPException(429, 'Queue full; please wait')
    conv_id = body.conversation_id
    if conv_id is not None:
        if db.execute("SELECT 1 FROM conversations WHERE id=? AND module='agent'", (conv_id,)).fetchone() is None:
            raise HTTPException(404, 'Conversation not found')
        if db.execute("SELECT 1 FROM agent_runs WHERE conversation_id=? AND status IN ('queued','running')", (conv_id,)).fetchone():
            raise HTTPException(409, 'This conversation already has an active task')
    # All writes happen without awaits; one transaction owns conversation+run.
    try:
        if conv_id is None:
            cursor = db.execute("INSERT INTO conversations(module,title,messages) VALUES ('agent',?,'[]')", (prompt[:80],))
            conv_id = cursor.lastrowid
        run_id = uuid.uuid4().hex
        db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status) VALUES (?,?,?,?,?,'queued')", (run_id,body.request_key,conv_id,body.skill,prompt))
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
    return view(db.execute('SELECT * FROM agent_runs WHERE id=?', (run_id,)).fetchone())

async def execute_run(run_id: str, state):
    db = get_conn(state.settings)
    try:
        async with state.agent_semaphore:
            row = db.execute('SELECT * FROM agent_runs WHERE id=?', (run_id,)).fetchone()
            past = db.execute("SELECT prompt,answer FROM agent_runs WHERE conversation_id=? AND status='succeeded' AND id<>? ORDER BY rowid DESC LIMIT 2", (row['conversation_id'],run_id)).fetchall()
            history = []
            for entry in reversed(past):
                history.extend([{'role':'user','content':entry['prompt']},{'role':'assistant','content':entry['answer']}])
            db.execute("UPDATE agent_runs SET status='running' WHERE id=?", (run_id,)); db.commit()
            try:
                async with client() as c:
                    response = await c.post('/run', json={'run_id':run_id,'skill':row['skill'],'prompt':row['prompt'],'history':history})
                    response.raise_for_status()
                    result = response.json()
                if result.get('status') not in ('succeeded','failed'):
                    raise ValueError('Invalid runner status')
            except (httpx.HTTPError, ValueError):
                result = {'status':'failed','error':'Agent connection failed or timed out; retry manually. No automatic retry was made.'}
            db.execute('UPDATE agent_runs SET status=?,answer=?,model=?,usage_json=?,tool_calls_json=?,metadata_json=?,cli_estimated_cost_usd=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?', (result['status'],str(result.get('answer') or ''),result.get('model'),json.dumps(result.get('usage') or {}),json.dumps(result.get('tool_calls') or [], ensure_ascii=False),json.dumps(result.get('metadata') or {}),result.get('cli_estimated_cost_usd'),result.get('error'),run_id))
            db.execute('UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (row['conversation_id'],))
            db.commit()
    except asyncio.CancelledError:
        db.rollback()
        db.execute("UPDATE agent_runs SET status='failed',error='Service stopped; retry manually',finished_at=CURRENT_TIMESTAMP WHERE id=?", (run_id,)); db.commit()
        raise
    finally:
        db.close()
