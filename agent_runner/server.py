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
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.catalog import SKILLS
from . import cli, jobs

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data' / 'agent'

engine: jobs.JobEngine | None = None


@asynccontextmanager
async def lifespan(app):
    global engine
    engine = jobs.JobEngine(RUNTIME, concurrency=int(os.getenv('RESEARCH_AGENT_CONCURRENCY', '2')), root=ROOT, env_loader=lambda rt: load_environment())
    await engine.start()
    try:
        yield
    finally:
        await engine.close()


app = FastAPI(title='Private Agent Runner', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

class RunRequest(BaseModel):
    run_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    skill: str
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


@app.get('/health')
async def health():
    queued, running = engine.counts() if engine else (0, 0)
    return {'status': 'ok', 'agent': 'claude_cli', 'model': current_model(load_environment()), 'concurrency': engine.concurrency if engine else 0, 'queued': queued, 'running': running, 'skills': [{'id': k, 'name': v['name'], 'version': '0.4.0'} for k, v in SKILLS.items()]}


@app.post('/runs', status_code=202)
async def submit_run(body: RunRequest):
    if body.skill not in SKILLS:
        raise HTTPException(400, 'Unknown skill')
    try:
        return await engine.submit(body.run_id, body.skill, body.model_dump())
    except jobs.QueueFull:
        raise HTTPException(429, 'Queue full; please wait')


@app.get('/runs/{run_id}')
async def get_run(run_id: str):
    got = engine.get(run_id)
    if got is None:
        raise HTTPException(404, 'Run not found')
    return got


@app.get('/runs/{run_id}/events')
async def run_events(run_id: str):
    if engine.get(run_id) is None:
        raise HTTPException(404, 'Run not found')

    def gen():
        async def stream():
            try:
                async for frame in engine.events(run_id):
                    yield f'data: {json.dumps(frame, ensure_ascii=False)}\n\n'
            except KeyError:
                return
        return stream()

    return StreamingResponse(gen(), media_type='text/event-stream')


@app.post('/runs/{run_id}/cancel')
async def cancel_run(run_id: str):
    got = await engine.cancel(run_id)
    if got is None:
        raise HTTPException(404, 'Run not found')
    return got
