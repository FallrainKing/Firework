"""Existing Claude CLI over a private Unix socket.

/run is the legacy synchronous wrapper (kept for rollback compatibility with
older app images; removed in plan 3). The async job engine lands in jobs.py.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.agent.catalog import SKILLS
from . import cli

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data' / 'agent'
TIMEOUT = 120

app = FastAPI(title='Private Agent Runner', docs_url=None, redoc_url=None, openapi_url=None)
_lock = asyncio.Lock()

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
    return {'status': 'ok', 'agent': 'claude_cli', 'model': current_model(load_environment()), 'busy': _lock.locked(), 'skills': [{'id': k, 'name': v['name'], 'version': '0.4.0'} for k, v in SKILLS.items()]}

@app.post('/run')
async def run(body: RunRequest):
    if body.skill not in SKILLS:
        raise HTTPException(400, 'Unknown skill')
    if _lock.locked():
        raise HTTPException(429, 'Agent is busy')
    async with _lock:
        skill = SKILLS[body.skill]
        run_folder = RUNTIME / 'runs' / body.run_id
        run_folder.mkdir(parents=True, mode=0o700, exist_ok=False)
        session_id = body.session_id or str(uuid.uuid4())
        folder = RUNTIME / 'sessions' / session_id
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        config_dir=RUNTIME/'claude-config';config_dir.mkdir(parents=True,mode=0o700,exist_ok=True)
        def transcript_exists():
            return any((config_dir/'projects').glob('*/'+session_id+'.jsonl'))
        resume=transcript_exists()
        if body.native_ready and not resume:
            raise HTTPException(409,'原生会话文件缺失；请恢复备份或明确创建新会话，不能静默丢失上下文')
        log_path = run_folder / 'tools.jsonl'
        allowed = skill['tools']
        env = load_environment()
        env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(skill['max_output_tokens'])
        mcp = {'mcpServers': {}}
        if allowed:
            mcp['mcpServers']['research'] = {'command': sys.executable, 'args': [str(ROOT / 'agent_runner/tools.py')], 'env': {'RESEARCH_DB_PATH': str(ROOT / 'data/app.db'), 'RESEARCH_TOOL_LOG': str(log_path), 'RESEARCH_ALLOWED_TOOLS': json.dumps(allowed), 'RESEARCH_PAPER_IDS':json.dumps(body.paper_ids), 'RESEARCH_MAX_TOOL_CALLS':str(skill['max_calls']), 'RESEARCH_IMPORT_ID':body.import_request_id or '', 'RESEARCH_RUN_ID':body.run_id, 'RESEARCH_TOKEN_FILE':str(RUNTIME/'internal-token')}}
        if body.skill=='paper_import':
            token=RUNTIME/'internal-token'
            if not token.exists():
                import secrets
                fd=os.open(token,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(32))
        model=current_model(env,vision=bool(body.attachment_ids))
        skill_md = (ROOT / 'skills' / body.skill / 'SKILL.md').read_text()
        blocks = image_blocks(body) if body.attachment_ids else []
        args = cli.build_args(skill, model, session_id, resume, mcp, skill_md, bool(blocks))
        history = [{'role': h.get('role'), 'content': str(h.get('content', ''))[:2000]} for h in body.history if h.get('role') in ('user', 'assistant')]
        input_bytes = cli.build_input(body, history, resume, blocks)
        proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=folder, env=env, start_new_session=True)
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(input_bytes), TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            await stop_process(proc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise HTTPException(504, 'Agent timed out after 120 seconds; no automatic retry')
        try:
            result = cli.parse_result(stdout)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(502, 'Agent returned invalid JSON; inspect host service status')
        calls = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
        return cli.build_payload(result, model=model, session_id=session_id, resume=resume, history=history, calls=calls, allowed=allowed, skill_id=body.skill, returncode=proc.returncode, native_ready=transcript_exists())
