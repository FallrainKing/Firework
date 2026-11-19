"""Existing Claude CLI over a private Unix socket.

/run is the legacy synchronous wrapper (kept for rollback compatibility with
older app images; removed in plan 3). The async job engine lands in jobs.py.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.catalog import SKILLS
from app.agent.protocol import RUNNER_PROTOCOL_VERSION
from . import cli, jobs
from app.core.workspaces import workspace_path,valid_workspace
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data' / 'agent'

engine: jobs.JobEngine | None = None
workspace_engines: dict[str, jobs.JobEngine] = {}
workspace_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    global engine
    workspace_engines.clear()
    engine = jobs.JobEngine(RUNTIME, concurrency=int(os.getenv('RESEARCH_AGENT_CONCURRENCY', '2')), root=ROOT, env_loader=lambda rt: load_environment())
    await engine.start()
    try:
        yield
    finally:
        for other in workspace_engines.values():
            await other.close()
        workspace_engines.clear()
        await engine.close()


app = FastAPI(title='Private Agent Runner', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

class RunRequest(BaseModel):
    run_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    skill: str
    skill_version_id: int | None = None
    skill_hash: str | None = Field(default=None, max_length=128)
    prompt: str = Field(min_length=1, max_length=3000)
    history: list[dict] = Field(default_factory=list, max_length=40)
    session_id: str | None = Field(None, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    native_ready: bool = False
    contexts: list[dict] = Field(default_factory=list,max_length=3)
    import_request_id: str | None = Field(None,pattern=r'^[a-f0-9]{32}$')
    attachment_ids: list[str] = Field(default_factory=list,max_length=3)
    paper_ids: list[int] = Field(default_factory=list, max_length=10)


# Thin wrappers keep the historical patch points (tests patch these on server).
def load_environment() -> dict:
    return cli.load_environment(RUNTIME)

current_model = cli.current_model
stop_process = cli.stop_process

def image_blocks(body):
    return cli.image_blocks(body, RUNTIME)


async def engine_for(request: Request):
    key=request.headers.get('x-research-workspace','legacy')
    if not valid_workspace(key):raise HTTPException(400,'Invalid workspace')
    if key=='legacy':return engine
    auth_db=RUNTIME.parent/'auth/accounts.db'
    if not auth_db.is_file():raise HTTPException(403,'Workspace unavailable')
    with sqlite3.connect(auth_db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        account=db.execute('SELECT enabled FROM accounts WHERE workspace_key=?',(key,)).fetchone()
    if not account or not account[0] or os.getenv('RESEARCH_AUTH_ADMIN_ONLY','1')!='0':
        raise HTTPException(403,'Workspace unavailable')
    if key in workspace_engines:return workspace_engines[key]
    async with workspace_lock:
        if key not in workspace_engines:
            runtime=workspace_path(RUNTIME.parent,key)/'agent'
            other=jobs.JobEngine(runtime,concurrency=engine.concurrency,root=ROOT)
            other._sem=engine._sem  # shared concurrency ceiling across accounts
            await other.start()
            workspace_engines[key]=other
    return workspace_engines[key]


@app.get('/health')
async def health(request: Request):
    current=await engine_for(request)
    queued, running = current.counts() if current else (0, 0)
    return {'status': 'ok', 'protocol_version': RUNNER_PROTOCOL_VERSION, 'agent': 'claude_cli', 'model': current_model(load_environment()), 'concurrency': engine.concurrency if engine else 0, 'queued': queued, 'running': running, 'skills': [{'id': k, 'name': v['name'], 'version': '0.4.0'} for k, v in SKILLS.items()]}


@app.post('/runs', status_code=202)
async def submit_run(body: RunRequest, request: Request):
    current=await engine_for(request)
    key=request.headers.get('x-research-workspace','legacy')
    payload = body.model_dump()
    if body.skill in SKILLS:
        policy = dict(SKILLS[body.skill])
        policy.update({'id': body.skill, 'name': policy['name'], 'version_id': None, 'version': '0.4.0', 'skill_hash': None, 'storage_key': '', 'entry': 'SKILL.md'})
    elif body.skill.startswith('custom:'):
        from app.core.config import Settings
        from app.core.db import get_conn
        from app.skills import service as skills_service
        settings = Settings(data_dir=current.runtime.parent,qdrant_url='unused',workspace_key=key)
        db = get_conn(settings)
        try:
            policy = skills_service.execution_policy(db, body.skill, body.skill_version_id)
        except ValueError:
            raise HTTPException(400, 'Unknown skill') from None
        finally:
            db.close()
        if body.skill_hash and body.skill_hash != policy['skill_hash']:
            raise HTTPException(409, 'Skill version changed; retry with the current version')
    else:
        raise HTTPException(400, 'Unknown skill')
    payload['skill_policy'] = policy
    payload['workspace_key'] = key
    try:
        if sum(sum(item.counts()) for item in [engine,*workspace_engines.values()]) >= jobs.MAX_ACTIVE and current.get(body.run_id) is None:
            raise jobs.QueueFull()
        return await current.submit(body.run_id, body.skill, payload)
    except jobs.QueueFull:
        raise HTTPException(429, 'Queue full; please wait')


@app.get('/runs/{run_id}')
async def get_run(run_id: str, request: Request):
    current=await engine_for(request)
    got = current.get(run_id)
    if got is None:
        raise HTTPException(404, 'Run not found')
    return got


@app.get('/runs/{run_id}/events')
async def run_events(run_id: str, request: Request):
    current=await engine_for(request)
    if current.get(run_id) is None:
        raise HTTPException(404, 'Run not found')

    def gen():
        async def stream():
            try:
                async for frame in current.events(run_id):
                    yield f'data: {json.dumps(frame, ensure_ascii=False)}\n\n'
            except KeyError:
                return
        return stream()

    return StreamingResponse(gen(), media_type='text/event-stream')


@app.post('/runs/{run_id}/cancel')
async def cancel_run(run_id: str, request: Request):
    current=await engine_for(request)
    got = await current.cancel(run_id)
    if got is None:
        raise HTTPException(404, 'Run not found')
    return got
