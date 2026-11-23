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
from pydantic import BaseModel, Field, SecretStr

from app.agent.catalog import SKILLS
from app.agent.protocol import RUNNER_PROTOCOL_VERSION
from . import cli, jobs
from app.runner_config.budgets import BudgetSnapshot, KEYS
from app.runner_config.connection_schemas import ConnectionSnapshot
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

from app.runner_config.profiles import ProfileRef

class RunRequest(BaseModel):
    profile_ref: ProfileRef | None = None
    budget_policy: BudgetSnapshot | None = None
    connection_snapshot: ConnectionSnapshot | None = None
    connection_secret: SecretStr | None = Field(None,exclude=True,repr=False)
    run_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    skill: str
    skill_version_id: int | None = None
    skill_hash: str | None = Field(default=None, max_length=128)
    prompt: str = Field(min_length=1, max_length=3000)
    history: list[dict] = Field(default_factory=list, max_length=100)
    material_manifest: list[dict] = Field(default_factory=list,max_length=20)
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
    model=None
    if request.headers.get('x-research-workspace','legacy')=='legacy' and request.headers.get('x-research-custom-connection')!='1':
        try:model=current_model(load_environment())
        except (OSError,ValueError):pass
    return {'status': 'ok', 'protocol_version': RUNNER_PROTOCOL_VERSION, 'agent': 'claude_cli', 'model': model, 'concurrency': engine.concurrency if engine else 0, 'queued': queued, 'running': running, 'skills': [{'id': k, 'name': v['name'], 'version': '0.4.0'} for k, v in SKILLS.items()]}


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
    if body.budget_policy:
        resolved=body.budget_policy.model_dump()
        policy.update({k:resolved[k] for k in KEYS})
        policy['budget_snapshot']=resolved
    if body.profile_ref:
        from app.core.config import Settings
        from app.core.db import get_conn
        from app.runner_config import profiles
        from app.core.errors import ServiceError
        settings=Settings(data_dir=current.runtime.parent,qdrant_url='unused',workspace_key=key)
        db=get_conn(settings)
        try:
            plan=profiles.resolve(db,settings,body.profile_ref)
            run=db.execute('SELECT execution_policy_json FROM agent_runs WHERE id=?',(body.run_id,)).fetchone()
            stored=json.loads(run[0]) if run else {}
            if stored.get('profile_snapshot')!=plan['snapshot']:raise HTTPException(409,'Profile snapshot mismatch')
            expected=plan['connection']
            actual=body.connection_snapshot.model_dump()|{'mode':'custom'} if body.connection_snapshot else {'mode':'legacy'}
            if actual!=expected:raise HTTPException(409,'Profile connection mismatch')
            if body.skill!=plan['policy']['id'] or body.skill_version_id!=plan['policy']['version_id'] or body.skill_hash!=plan['policy']['skill_hash']:raise HTTPException(409,'Profile Skill mismatch')
            if not body.budget_policy or body.budget_policy.model_dump()!=plan['policy']['budget_snapshot']:raise HTTPException(409,'Profile budget mismatch')
            policy=plan['policy']
            policy['profile_snapshot']=plan['snapshot']
            policy['role_prompt']=plan['role_prompt']
        except ServiceError as e:raise HTTPException(e.status,e.detail) from None
        finally:db.close()
    if body.connection_snapshot:
        if body.connection_secret is None:raise HTTPException(422,'Connection credential required')
        payload['_connection_secret']=body.connection_secret.get_secret_value()
    elif key!='legacy':raise HTTPException(403,'Own API connection required')
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
    native=current.terminals.for_run(run_id)
    if native:
        await current.terminals.stop(native[0],native[1]['generation'])
        return {'run_id':run_id,'status':'cancelled'}
    got = await current.cancel(run_id)
    if got is None:
        raise HTTPException(404, 'Run not found')
    return got


@app.get('/native/sessions/{conversation_id}')
async def native_session(conversation_id:int,request:Request,offset:int=0,source:str|None=None,limit:int=50):
    if offset<0 or not 1<=limit<=100 or (source and not __import__('re').fullmatch('[a-f0-9]{32}',source)):
        raise HTTPException(422,'Invalid transcript cursor')
    current=await engine_for(request)
    from .native import transcript
    primary=request.headers.get('x-research-workspace','legacy')=='legacy'
    data=await asyncio.to_thread(transcript,current.runtime,conversation_id,offset,source,limit,primary)
    if primary:
        from .connections import redact
        try:env=current._env_loader(current.runtime)
        except (OSError,ValueError):raise HTTPException(503,'无法核验凭据脱敏') from None
        for key in ('ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN'):
            data=redact(data,env.get(key))
    return data


@app.get('/providers')
async def providers(request:Request):
    await engine_for(request)
    from .native import provider_status
    return {'providers':[await provider_status()]}


class TerminalStart(BaseModel):
    controller_id:str=Field(pattern='^[a-f0-9]{32}$')
    connection_snapshot: ConnectionSnapshot | None = None
    connection_secret: SecretStr | None = Field(None,exclude=True,repr=False)

class TerminalInput(BaseModel):
    generation: str = Field(pattern='^[a-f0-9]{32}$')
    request_key: str = Field(pattern='^[a-f0-9]{32}$')
    controller_id:str=Field(pattern='^[a-f0-9]{32}$')
    data: str = Field(min_length=1,max_length=32768)

class TerminalControl(BaseModel):
    controller_id:str=Field(pattern='^[a-f0-9]{32}$')
    generation: str = Field(pattern='^[a-f0-9]{32}$')

class TerminalResize(TerminalControl):
    cols:int=Field(ge=20,le=240)
    rows:int=Field(ge=10,le=100)

@app.get('/terminal-capabilities')
async def terminal_capabilities(request:Request):
    await engine_for(request)
    from .terminal import availability
    return await availability()

@app.post('/terminals/{ident}/start')
async def terminal_start(ident:int,body:TerminalStart,request:Request):
    current=await engine_for(request)
    payload=body.model_dump()
    if body.connection_secret:payload['connection_secret']=body.connection_secret.get_secret_value()
    return await current.terminals.start(ident,payload,request.headers.get('x-research-workspace','legacy')=='legacy')

@app.get('/terminals/{ident}')
async def terminal_read(ident:int,request:Request,offset:int=0,generation:str|None=None,controller_id:str|None=None):
    if offset<0:raise HTTPException(422,'Invalid cursor')
    return (await engine_for(request)).terminals.read(ident,offset,generation,controller_id)

@app.post('/terminals/{ident}/input')
async def terminal_input(ident:int,body:TerminalInput,request:Request):
    return await (await engine_for(request)).terminals.input(ident,body.model_dump())

@app.post('/terminals/{ident}/resize')
async def terminal_resize(ident:int,body:TerminalResize,request:Request):
    return await (await engine_for(request)).terminals.resize(ident,body.model_dump())

@app.post('/terminals/{ident}/stop')
async def terminal_stop(ident:int,body:TerminalControl,request:Request):
    return await (await engine_for(request)).terminals.stop(ident,body.generation,controller_id=body.controller_id)

class ConnectionProbe(BaseModel):
    id:str=Field(pattern='^[a-f0-9]{32}$')
    kind:str=Field(pattern='^(network|model)$')
    connection_snapshot:ConnectionSnapshot
    connection_secret:SecretStr=Field(exclude=True,repr=False)

probe_tasks={}
probe_cancelled=set()
@app.post('/connection-tests')
async def connection_probe(body:ConnectionProbe,request:Request):
    from .connection_probe import probe
    from .connections import check_current
    current=await engine_for(request);snapshot=body.connection_snapshot.model_dump()
    try:check_current(current.runtime,snapshot)
    except ValueError:raise HTTPException(409,'连接修订已变化') from None
    key=(str(current.runtime),body.id)
    if key in probe_cancelled:return {'status':'cancelled','model_called':False}
    if key in probe_tasks:raise HTTPException(409,'测试已经存在')
    if sum(1 for k in probe_tasks if k[0]==key[0])>=2:raise HTTPException(429,'最多同时测试两个连接')
    task=asyncio.create_task(asyncio.wait_for(probe(snapshot,body.connection_secret.get_secret_value(),body.kind),30));probe_tasks[key]=task
    try:return await task
    except asyncio.CancelledError:return {'status':'cancelled','model_called':body.kind=='model'}
    except asyncio.TimeoutError:return {'status':'failed','reason':'timeout','model_called':body.kind=='model'}
    finally:probe_tasks.pop(key,None)

@app.post('/connection-tests/{ident}/cancel')
async def cancel_probe(ident:str,request:Request):
    current=await engine_for(request);key=(str(current.runtime),ident)
    if len(probe_cancelled)>1000:probe_cancelled.clear()
    probe_cancelled.add(key);task=probe_tasks.get(key)
    if task:task.cancel()
    return {'status':'cancelled'}
