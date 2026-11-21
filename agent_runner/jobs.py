"""Async job engine: queue, bounded concurrency, streaming events, cancel.

Each run is an asyncio task driving one Claude CLI subprocess. Progress and
terminal frames are appended to runs/<id>/events.jsonl and fanned out to SSE
subscribers; result.json/status.json make state survive engine restarts
(interrupted runs are marked failed on start, never auto-replayed).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

from . import cli

ROOT = Path(__file__).resolve().parents[1]
MAX_ACTIVE = 8
NATIVE_MISSING = '原生会话文件缺失；请恢复备份或明确创建新会话，不能静默丢失上下文'
TERMINAL = ('succeeded', 'failed', 'cancelled')


class QueueFull(Exception):
    """queued+running reached MAX_ACTIVE."""


class _Body:
    """Attribute view over a RunRequest dump for cli helpers."""

    def __init__(self, data: dict):
        self.__dict__.update(data)


def _subset(event: dict) -> dict:
    out = {'type': event.get('type')}
    content = (event.get('message') or {}).get('content') or []
    tools = [b.get('name') for b in content if isinstance(b, dict) and b.get('type') == 'tool_use']
    texts = [b.get('text', '')[:200] for b in content if isinstance(b, dict) and b.get('type') == 'text']
    if tools:
        out['tools'] = tools
    if texts:
        out['text'] = ' '.join(texts)[:400]
    if event.get('subtype'):
        out['subtype'] = event['subtype']
    return out


class JobEngine:
    def __init__(self, runtime, concurrency=2, root=ROOT, env_loader=None):
        self.runtime = Path(runtime)
        self.root = Path(root)
        self.concurrency = concurrency
        self._env_loader = env_loader or (lambda rt: cli.load_environment(rt))
        self._sem = asyncio.Semaphore(concurrency)
        self._jobs: dict[str, dict] = {}

    async def start(self):
        runs = self.runtime / 'runs'
        if not runs.exists():
            return
        for folder in runs.iterdir():
            sp = folder / 'status.json'
            if not sp.exists():
                continue
            if json.loads(sp.read_text()).get('status') in ('queued', 'running'):
                self._write_terminal(folder, {'status': 'failed', 'error': 'Runner restarted; run interrupted', 'answer': '', 'usage': {}, 'tool_calls': [], 'metadata': {}})

    def _folder(self, run_id):
        return self.runtime / 'runs' / run_id

    def _write_status(self, folder, status):
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        (folder / 'status.json').write_text(json.dumps({'status': status}))

    def _append_event(self, folder, frame):
        with (folder / 'events.jsonl').open('a') as f:
            f.write(json.dumps(frame, ensure_ascii=False) + '\n')

    def _write_terminal(self, folder, payload):
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        (folder / 'result.json').write_text(json.dumps(payload, ensure_ascii=False))
        (folder / 'status.json').write_text(json.dumps({'status': payload['status']}))
        self._append_event(folder, {'type': 'result', 'result': payload})

    def counts(self):
        queued = sum(1 for j in self._jobs.values() if j['status'] == 'queued')
        running = sum(1 for j in self._jobs.values() if j['status'] == 'running')
        return queued, running

    async def submit(self, run_id, skill_id, body: dict) -> dict:
        from app.agent.catalog import SKILLS

        if skill_id not in SKILLS and 'skill_policy' not in body:
            raise ValueError('Unknown skill')
        if run_id in self._jobs:
            return {'run_id': run_id, 'status': self._jobs[run_id]['status']}
        folder = self._folder(run_id)
        if (folder / 'status.json').exists():
            return {'run_id': run_id, 'status': json.loads((folder / 'status.json').read_text())['status']}
        queued, running = self.counts()
        if queued + running >= MAX_ACTIVE:
            raise QueueFull()
        job = {'run_id': run_id, 'skill': skill_id, 'body': body, 'status': 'queued', 'progress': None, 'result': None, 'subs': set(), 'proc': None, 'result_event': None, 'error_status': None, 'usage_acc': {}, 'shutdown': False}
        self._jobs[run_id] = job
        self._write_status(folder, 'queued')
        job['task'] = asyncio.create_task(self._run_job(job))
        return {'run_id': run_id, 'status': 'queued'}

    def get(self, run_id):
        job = self._jobs.get(run_id)
        if job:
            return {'run_id': run_id, 'status': job['status'], 'progress': job['progress'], 'result': job['result']}
        folder = self._folder(run_id)
        if not (folder / 'status.json').exists():
            return None
        status = json.loads((folder / 'status.json').read_text())['status']
        rp = folder / 'result.json'
        result = json.loads(rp.read_text()) if rp.exists() else None
        progress = None
        ep = folder / 'events.jsonl'
        if ep.exists():
            for line in ep.read_text().splitlines():
                if line.strip():
                    frame = json.loads(line)
                    if frame.get('type') == 'progress':
                        progress = frame['event']
        return {'run_id': run_id, 'status': status, 'progress': progress, 'result': result}

    async def cancel(self, run_id):
        job = self._jobs.get(run_id)
        if job is None:
            got = self.get(run_id)
            return {'run_id': run_id, 'status': got['status']} if got else None
        if job['status'] in TERMINAL:
            return {'run_id': run_id, 'status': job['status']}
        job['task'].cancel()
        if job['status'] == 'queued':
            self._terminal(job, {'status': 'cancelled', 'error': '已取消', 'answer': '', 'usage': {}, 'tool_calls': [], 'metadata': {}})
            return {'run_id': run_id, 'status': 'cancelled'}
        return {'run_id': run_id, 'status': job['status']}

    async def events(self, run_id):
        job = self._jobs.get(run_id)
        folder = self._folder(run_id)
        if job is None and not (folder / 'status.json').exists():
            raise KeyError(run_id)
        ep = folder / 'events.jsonl'
        saw_result = False
        if ep.exists():
            for line in ep.read_text().splitlines():
                if line.strip():
                    frame = json.loads(line)
                    saw_result = saw_result or frame.get('type') == 'result'
                    yield frame
        if saw_result or job is None or job['status'] in TERMINAL:
            return
        q: asyncio.Queue = asyncio.Queue()
        job['subs'].add(q)
        try:
            if job['status'] in TERMINAL:
                yield {'type': 'result', 'result': job['result']}
                return
            while True:
                frame = await q.get()
                yield frame
                if frame.get('type') == 'result':
                    return
        finally:
            job['subs'].discard(q)

    async def close(self):
        # Graceful shutdown is a restart, not a user cancel: interrupted runs
        # must read as failed, never as "已取消".
        for j in self._jobs.values():
            if j['status'] not in TERMINAL:
                j['shutdown'] = True
        tasks = [j['task'] for j in self._jobs.values() if not j['task'].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _progress(self, job, event):
        job['progress'] = event
        frame = {'type': 'progress', 'event': event}
        self._append_event(self._folder(job['run_id']), frame)
        for q in list(job['subs']):
            q.put_nowait(frame)

    def _terminal(self, job, payload):
        if job['status'] in TERMINAL:
            return
        job['status'] = payload['status']
        job['result'] = payload
        self._write_terminal(self._folder(job['run_id']), payload)
        for q in list(job['subs']):
            q.put_nowait({'type': 'result', 'result': payload})

    async def _run_job(self, job):
        from app.agent.catalog import SKILLS

        skill = job['body'].get('skill_policy') or SKILLS[job['skill']]
        body = job['body']
        folder = self._folder(job['run_id'])
        proc = None
        partial_text = ''
        timeout_s = skill['timeout_s']
        try:
            async with self._sem:
                if job['status'] != 'queued':
                    return
                job['status'] = 'running'
                self._write_status(folder, 'running')
                session_id = body.get('session_id') or str(uuid.uuid4())
                sfolder = self.runtime / 'sessions' / session_id
                sfolder.mkdir(parents=True, mode=0o700, exist_ok=True)
                config_dir = self.runtime / 'claude-config'
                config_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

                def transcript_exists():
                    return any((config_dir / 'projects').glob('*/' + session_id + '.jsonl'))

                resume = transcript_exists()
                if body.get('native_ready') and not resume:
                    job['error_status'] = 409
                    self._terminal(job, {'status': 'failed', 'error': NATIVE_MISSING, 'answer': '', 'usage': {}, 'tool_calls': [], 'metadata': {}})
                    return
                log_path = folder / 'tools.jsonl'
                allowed = skill['tools']
                env = self._env_loader(self.runtime)
                env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(skill['max_output_tokens'])
                mcp = {'mcpServers': {}}
                if allowed:
                    tool_env = {'RESEARCH_DB_PATH': str(self.runtime.parent / 'app.db'), 'RESEARCH_TOOL_LOG': str(log_path), 'RESEARCH_ALLOWED_TOOLS': json.dumps(allowed), 'RESEARCH_PAPER_IDS': json.dumps(body.get('paper_ids') or []), 'RESEARCH_MAX_TOOL_CALLS': str(skill['max_calls']), 'RESEARCH_IMPORT_ID': body.get('import_request_id') or '', 'RESEARCH_RUN_ID': job['run_id'], 'RESEARCH_TOKEN_FILE': str(self.runtime / 'internal-token'), 'RESEARCH_WORKSPACE': body.get('workspace_key','legacy')}
                    if 'skill_resource' in allowed and skill.get('storage_key'):
                        tool_env['RESEARCH_SKILL_ROOT'] = str(self.runtime.parent / 'skills' / skill['storage_key'])
                        tool_env['RESEARCH_SKILL_HASH'] = str(skill.get('skill_hash') or '')
                        tool_env['RESEARCH_SKILL_VERSION_ID'] = str(skill.get('version_id') or '')
                    if job['skill'] in ('frontier_monitor','paper_guide'):
                        tool_env['RESEARCH_SKILL_ROOT'] = str(self.root / 'skills' / job['skill'])
                    mcp['mcpServers']['research'] = {'command': sys.executable, 'args': [str(self.root / 'agent_runner/tools.py')], 'env': tool_env}
                if any(name in allowed for name in ('paper_import','frontier_context','reader_guide_context')):
                    token = self.runtime / 'internal-token'
                    if not token.exists():
                        try:
                            fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        except FileExistsError:
                            pass
                        else:
                            with os.fdopen(fd, 'w') as f:
                                f.write(secrets.token_urlsafe(32))
                model = cli.current_model(env, vision=bool(body.get('attachment_ids')))
                skill_md = ((self.runtime.parent / 'skills' / skill['storage_key'] / skill['entry']).read_text() if skill.get('storage_key') else (self.root / 'skills' / job['skill'] / 'SKILL.md').read_text())
                req = _Body(body)
                blocks = cli.image_blocks(req, self.runtime) if body.get('attachment_ids') else []
                args = cli.build_args(skill, model, session_id, resume, mcp, skill_md, bool(blocks))
                history = [{'role': h.get('role'), 'content': str(h.get('content', ''))[:2000]} for h in body.get('history') or [] if h.get('role') in ('user', 'assistant')]
                input_bytes = cli.build_input(req, history, resume, blocks)
                # Large stream limit: CJK tool results can exceed the 64KiB
                # default in a single stream-json line. stderr must be drained
                # concurrently or a chatty CLI deadlocks once the pipe fills.
                proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=sfolder, env=env, start_new_session=True, limit=10 * 1024 * 1024)
                job['proc'] = proc

                partial_text = ''
                async def monitor():
                    nonlocal partial_text
                    proc.stdin.write(input_bytes)
                    await proc.stdin.drain()
                    proc.stdin.write_eof()

                    async def drain_stderr():
                        try:
                            async for _ in proc.stderr:
                                pass
                        except Exception:
                            pass  # diagnostics are expendable; never kill the job

                    drainer = asyncio.create_task(drain_stderr())
                    try:
                        async for raw in proc.stdout:
                            line = raw.decode().strip()
                            if not line:
                                continue
                            event = json.loads(line)
                            if event.get('type') == 'result':
                                job['result_event'] = event
                            elif event.get('type') in ('assistant', 'user', 'system'):
                                if event.get('type') == 'assistant':
                                    texts=[b.get('text','') for b in (event.get('message') or {}).get('content',[]) if b.get('type')=='text']
                                    if texts: partial_text='\n'.join(texts)[-20000:]
                                    usage = (event.get('message') or {}).get('usage') or {}
                                    for k, v in usage.items():
                                        if isinstance(v, (int, float)):
                                            job['usage_acc'][k] = job['usage_acc'].get(k, 0) + v
                                self._progress(job, _subset(event))
                        await proc.wait()
                    finally:
                        drainer.cancel()
                        try:
                            await drainer
                        except asyncio.CancelledError:
                            pass

                if timeout_s is None:
                    await monitor()
                else:
                    await asyncio.wait_for(monitor(), timeout_s)
                calls = [json.loads(l) for l in log_path.read_text().splitlines()] if log_path.exists() else []
                payload = cli.build_payload(job['result_event'] or {}, model=model, session_id=session_id, resume=resume, history=history, calls=calls, allowed=allowed, skill_id=job['skill'], returncode=proc.returncode, native_ready=transcript_exists())
                if payload['status']=='failed' and partial_text and not payload.get('answer'):
                    payload['answer']=partial_text
                    payload['metadata']['partial_answer']=True
                self._terminal(job, payload)
        except asyncio.TimeoutError:
            if proc:
                await cli.stop_process(proc)
            self._terminal(job, {'status': 'failed', 'error': f'Agent timed out after {timeout_s} seconds; no automatic retry', 'answer': partial_text, 'usage': (job['result_event'] or {}).get('usage') or job['usage_acc'], 'tool_calls': [], 'metadata': {'partial_answer':bool(partial_text)}})
        except asyncio.CancelledError:
            if proc:
                await cli.stop_process(proc)
            usage = (job['result_event'] or {}).get('usage') or job['usage_acc']
            if job.get('shutdown'):
                self._terminal(job, {'status': 'failed', 'error': 'Runner restarted; run interrupted', 'answer': '', 'usage': usage, 'tool_calls': [], 'metadata': {}})
            else:
                self._terminal(job, {'status': 'cancelled', 'error': '已取消', 'answer': '', 'usage': usage, 'tool_calls': [], 'metadata': {}})
        except Exception as exc:
            if proc:
                await cli.stop_process(proc)
            self._terminal(job, {'status': 'failed', 'error': f'Runner job failed: {type(exc).__name__}: {exc}'[:250], 'answer': '', 'usage': {}, 'tool_calls': [], 'metadata': {}})
