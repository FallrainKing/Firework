"""Runner job engine: queue, streaming progress, cancel, per-skill timeouts."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_runner import cli, jobs as jobs_mod


def result_line(text='done', **kw):
    return json.dumps({'type': 'result', 'subtype': 'success', 'result': text,
                       'usage': {'input_tokens': 5, 'output_tokens': 2}, **kw})


def make_spawn(lines, delays=None, hang=False, capture=None, stderr_bytes=b''):
    delays = delays or {}

    async def spawn(*args, **kwargs):
        if capture is not None:
            capture.update(args=args, kwargs=kwargs)
        reader = asyncio.StreamReader(limit=kwargs.get('limit', 64 * 1024))
        err = asyncio.StreamReader(limit=kwargs.get('limit', 64 * 1024))
        err.feed_data(stderr_bytes)
        err.feed_eof()

        class Stdin:
            data = b''
            def write(self, b): self.data += b
            async def drain(self): pass
            def write_eof(self): pass

        class Proc:
            pid = 4242
            returncode = None
            stdout = reader
            stderr = err
            stdin = Stdin()
            async def wait(self):
                await self._feed
                self.returncode = 0
                return 0

        proc = Proc()

        async def feed():
            for i, line in enumerate(lines):
                if i in delays:
                    await asyncio.sleep(delays[i])
                reader.feed_data(line.encode() + b'\n')
            if not hang:
                reader.feed_eof()

        proc._feed = asyncio.create_task(feed())
        return proc

    return spawn


@pytest.fixture
def runtime(tmp_path):
    rt = tmp_path / 'agent'
    (rt / 'runs').mkdir(parents=True)
    for skill in ('chat', 'paper_read', 'search_library'):
        d = tmp_path / 'skills' / skill
        d.mkdir(parents=True)
        (d / 'SKILL.md').write_text('skill instructions')
    return rt


@pytest.fixture
def engine(runtime, monkeypatch):
    monkeypatch.setattr(cli.os, 'killpg', lambda pid, sig: None)
    return jobs_mod.JobEngine(runtime, concurrency=2, root=runtime.parent, env_loader=lambda rt: {})


def body(**kw):
    base = {'prompt': 'hi', 'history': [], 'session_id': None, 'native_ready': False,
            'contexts': [], 'attachment_ids': [], 'paper_ids': [], 'import_request_id': None}
    base.update(kw)
    return base


def test_submit_streams_progress_and_result(engine, runtime, monkeypatch):
    lines = [json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'thinking'}]}}),
             result_line('answer text')]
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn(lines))

    async def main():
        await engine.start()
        sub = await engine.submit('a' * 32, 'chat', body())
        assert sub['status'] in ('queued', 'running')
        frames = [f async for f in engine.events('a' * 32)]
        assert frames[-1]['type'] == 'result'
        payload = frames[-1]['result']
        assert payload['status'] == 'succeeded' and payload['answer'] == 'answer text'
        assert payload['usage']['input_tokens'] == 5
        assert any(f['type'] == 'progress' for f in frames)
        assert (runtime / 'runs' / ('a' * 32) / 'result.json').exists()
        got = engine.get('a' * 32)
        assert got['status'] == 'succeeded' and got['result']['answer'] == 'answer text'
        await engine.close()

    asyncio.run(main())


def test_no_hard_timeout_for_reading_skill(engine, runtime, monkeypatch):
    from app.agent.catalog import SKILLS
    monkeypatch.setitem(SKILLS['chat'], 'timeout_s', 0.1)
    monkeypatch.setitem(SKILLS['paper_read'], 'timeout_s', None)
    lines = [result_line('slow answer')]
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn(lines, delays={0: 0.3}))

    async def main():
        await engine.start()
        await engine.submit('b' * 32, 'chat', body())
        await engine.submit('c' * 32, 'paper_read', body(paper_ids=[1]))
        # reading skills require a successful tool call before the answer is trusted
        (runtime / 'runs' / ('c' * 32) / 'tools.jsonl').write_text(json.dumps({'tool': 'paper_read', 'ok': True}) + '\n')
        chat = [f async for f in engine.events('b' * 32)][-1]['result']
        read = [f async for f in engine.events('c' * 32)][-1]['result']
        assert chat['status'] == 'failed' and 'timed out' in chat['error']
        assert read['status'] == 'succeeded' and read['answer'] == 'slow answer'
        await engine.close()

    asyncio.run(main())


def test_cancel_kills_and_preserves_usage(engine, monkeypatch):
    killed = []
    monkeypatch.setattr(cli.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    lines = [result_line('partial')]
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn(lines, delays={0: 0.2}, hang=True))

    async def main():
        await engine.start()
        await engine.submit('d' * 32, 'chat', body())
        for _ in range(100):
            if engine.get('d' * 32)['status'] == 'running':
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)  # let the result event arrive, stdout stays open
        await engine.cancel('d' * 32)
        frames = [f async for f in engine.events('d' * 32)]
        payload = frames[-1]['result']
        assert payload['status'] == 'cancelled'
        assert payload['usage']['input_tokens'] == 5
        assert killed and killed[0][0] == 4242
        await engine.close()

    asyncio.run(main())


def test_concurrency_and_queue(runtime, monkeypatch):
    monkeypatch.setattr(cli.os, 'killpg', lambda pid, sig: None)
    eng = jobs_mod.JobEngine(runtime, concurrency=1, root=runtime.parent, env_loader=lambda rt: {})
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn([], hang=True))

    async def main():
        await eng.start()
        for i in range(8):
            await eng.submit(f'{i:032x}', 'chat', body())
        with pytest.raises(jobs_mod.QueueFull):
            await eng.submit('f' * 32, 'chat', body())
        await asyncio.sleep(0.05)
        statuses = [eng.get(f'{i:032x}')['status'] for i in range(8)]
        assert statuses.count('running') == 1 and statuses.count('queued') == 7
        await eng.cancel('0' * 32)
        await asyncio.sleep(0.05)
        assert eng.get(f'{1:032x}')['status'] == 'running'
        for i in range(8):
            await eng.cancel(f'{i:032x}')
        await eng.close()

    asyncio.run(main())


def test_restart_marks_interrupted_failed(engine, runtime):
    folder = runtime / 'runs' / ('e' * 32)
    folder.mkdir(parents=True)
    (folder / 'status.json').write_text(json.dumps({'status': 'running'}))

    async def main():
        await engine.start()
        got = engine.get('e' * 32)
        assert got['status'] == 'failed' and 'restart' in got['result']['error'].lower()
        await engine.close()

    asyncio.run(main())


def test_large_stderr_and_long_lines_do_not_hang(engine, monkeypatch):
    big_line = json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'text': 'x' * 70000}]}})
    capture = {}
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec',
                        make_spawn([big_line, result_line('ok')], capture=capture, stderr_bytes=b'e' * 200000))

    async def main():
        await engine.start()
        await engine.submit('a' * 32, 'chat', body())
        frames = [f async for f in engine.events('a' * 32)]
        assert frames[-1]['result']['status'] == 'succeeded'
        assert capture['kwargs'].get('limit', 0) >= 1024 * 1024
        await engine.close()

    asyncio.run(main())


def test_close_marks_running_failed_not_cancelled(engine, monkeypatch):
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn([], hang=True))

    async def main():
        await engine.start()
        await engine.submit('b' * 32, 'chat', body())
        for _ in range(100):
            if engine.get('b' * 32)['status'] == 'running':
                break
            await asyncio.sleep(0.01)
        await engine.close()
        got = engine.get('b' * 32)
        assert got['status'] == 'failed' and 'interrupted' in got['result']['error'].lower()

    asyncio.run(main())


def test_cancel_preserves_accumulated_usage(engine, monkeypatch):
    monkeypatch.setattr(cli.os, 'killpg', lambda pid, sig: None)
    assistant = json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 100, 'output_tokens': 20}, 'content': [{'type': 'text', 'text': 'hi'}]}})
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn([assistant], hang=True))

    async def main():
        await engine.start()
        await engine.submit('c' * 32, 'chat', body())
        for _ in range(200):
            got = engine.get('c' * 32)
            if got['status'] == 'running' and got['progress']:
                break
            await asyncio.sleep(0.01)
        await engine.cancel('c' * 32)
        frames = [f async for f in engine.events('c' * 32)]
        payload = frames[-1]['result']
        assert payload['status'] == 'cancelled'
        assert payload['usage']['input_tokens'] == 100 and payload['usage']['output_tokens'] == 20
        await engine.close()

    asyncio.run(main())


def test_legacy_run_wrapper_and_http_protocol(runtime, monkeypatch):
    from agent_runner import server
    monkeypatch.setattr(server, 'RUNTIME', runtime)
    monkeypatch.setattr(server, 'load_environment', lambda: {})
    monkeypatch.setattr(cli.os, 'killpg', lambda pid, sig: None)
    lines = [result_line('legacy answer')]
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn(lines))
    with TestClient(server.app) as c:
        r = c.post('/run', json={'run_id': '1' * 32, 'skill': 'chat', 'prompt': 'hi'})
        assert r.status_code == 200 and r.json()['status'] == 'succeeded'
        assert r.json()['answer'] == 'legacy answer'
        h = c.get('/health').json()
        assert h['concurrency'] == 2 and 'queued' in h and 'running' in h
        sub = c.post('/runs', json={'run_id': '2' * 32, 'skill': 'chat', 'prompt': 'hi'})
        assert sub.status_code == 202 and sub.json()['run_id'] == '2' * 32
        got = c.get('/runs/' + '2' * 32)
        assert got.status_code == 200 and got.json()['status'] in ('queued', 'running', 'succeeded')
        assert c.get('/runs/' + '9' * 32).status_code == 404
        ev = c.get('/runs/' + '2' * 32 + '/events')
        assert ev.status_code == 200 and ev.headers['content-type'].startswith('text/event-stream')
        assert 'data: ' in ev.text and '"type": "result"' in ev.text.replace('"type":"result"', '"type": "result"')
        cancel = c.post('/runs/' + '2' * 32 + '/cancel')
        assert cancel.status_code == 200 and cancel.json()['run_id'] == '2' * 32
        assert c.post('/runs/' + '9' * 32 + '/cancel').status_code == 404
