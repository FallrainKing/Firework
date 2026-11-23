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


def test_http_protocol(runtime, monkeypatch):
    from agent_runner import server
    monkeypatch.setattr(server, 'RUNTIME', runtime)
    monkeypatch.setattr(server, 'load_environment', lambda: {})
    monkeypatch.setattr(cli.os, 'killpg', lambda pid, sig: None)
    lines = [result_line('async answer')]
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn(lines))
    with TestClient(server.app) as c:
        assert c.post('/run', json={'run_id': '1' * 32, 'skill': 'chat', 'prompt': 'hi'}).status_code == 404
        h = c.get('/health').json()
        assert h['concurrency'] == 2 and 'queued' in h and 'running' in h
        from app.agent.protocol import RUNNER_PROTOCOL_VERSION
        assert h['protocol_version'] == RUNNER_PROTOCOL_VERSION
        invalid = c.post('/runs', json={'run_id': '0' * 32, 'skill': 'chat', 'skill_version_id': 'invalid', 'skill_hash': []})
        assert invalid.status_code == 422
        fields = {error['loc'][-1] for error in invalid.json()['detail']}
        assert {'prompt', 'skill_version_id', 'skill_hash'} <= fields
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


def test_account_runner_sessions_and_run_lookup_are_isolated(tmp_path,monkeypatch):
    import sqlite3
    from app.auth.store import AuthStore
    from agent_runner import server
    from app.core.config import Settings
    from app.core.db import get_conn
    root=tmp_path/'project';runtime=root/'data/agent';runtime.mkdir(parents=True)
    (root/'skills/chat').mkdir(parents=True);(root/'skills/chat/SKILL.md').write_text('Only own account')
    auth=AuthStore(root/'data',admin_only=False)
    first='a'*32;second='b'*32
    for i,key in enumerate((first,second)):
        auth.db.execute("INSERT INTO accounts(id,username,password_hash,role,enabled,workspace_key,created_at) VALUES (?,?,?,'user',1,?,0)",(str(i),'reader-'+str(i),'unused',key))
        settings=Settings(data_dir=root/'data/accounts'/key,qdrant_url='unused',workspace_key=key)
        db=get_conn(settings);db.close()
    auth.db.commit();auth.close()
    monkeypatch.setenv('RESEARCH_AUTH_ADMIN_ONLY','0')
    monkeypatch.setattr(server,'ROOT',root);monkeypatch.setattr(server,'RUNTIME',runtime)
    monkeypatch.setattr(server,'load_environment',lambda:{})
    monkeypatch.setattr(cli,'load_environment',lambda rt:{'CLAUDE_CONFIG_DIR':str(rt/'claude-config')})
    monkeypatch.setattr(cli.os,'killpg',lambda pid,sig:None)
    captures=[]
    fake=make_spawn([result_line('private result')])
    async def spawn(*args,**kwargs):captures.append(kwargs);return await fake(*args,**kwargs)
    monkeypatch.setattr(jobs_mod.asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setattr(jobs_mod.connections,'check_current',lambda *a:None)
    monkeypatch.setattr(jobs_mod.connections,'validate_destination',lambda *a:None)
    with TestClient(server.app) as c:
        rid='c'*32;sid='11111111-1111-4111-8111-111111111111'
        assert c.post('/runs',headers={'X-Research-Workspace':first},json={'run_id':rid,'skill':'chat','prompt':'no own connection'}).status_code==403
        payload={'run_id':rid,'skill':'chat','prompt':'read only own','session_id':sid,'connection_snapshot':{'id':'d'*32,'name':'own','revision':1,'base_url':'https://api.example.com','model':'test','auth_type':'api_key','vision':'unknown','context_window':200000,'role_prompt':''},'connection_secret':'test-only-own-key'}
        assert c.post('/runs',headers={'X-Research-Workspace':first},json=payload).status_code==202
        assert c.get('/runs/'+rid,headers={'X-Research-Workspace':second}).status_code==404
        assert c.post('/runs/'+rid+'/cancel',headers={'X-Research-Workspace':second}).status_code==404
        assert c.get('/runs/'+rid+'/events',headers={'X-Research-Workspace':second}).status_code==404
        assert c.post('/runs',headers={'X-Research-Workspace':second},json=payload).status_code==202
        c.get('/runs/'+rid+'/events',headers={'X-Research-Workspace':first})
        c.get('/runs/'+rid+'/events',headers={'X-Research-Workspace':second})
        assert len(captures)==2
        assert captures[0]['cwd']!=captures[1]['cwd']
        assert captures[0]['env']['CLAUDE_CONFIG_DIR']!=captures[1]['env']['CLAUDE_CONFIG_DIR']
        assert server.workspace_engines[first]._sem is server.workspace_engines[second]._sem
        assert c.get('/health',headers={'X-Research-Workspace':'../legacy'}).status_code==400


def test_custom_skill_files_use_the_account_runtime_not_global_data(engine,runtime,monkeypatch):
    own=runtime.parent/'skills/packages/private-v1';own.mkdir(parents=True)
    (own/'SKILL.md').write_text('Account-private skill instructions')
    capture={}
    monkeypatch.setattr(jobs_mod.asyncio,'create_subprocess_exec',make_spawn([result_line('done')],capture=capture))
    policy={'id':'custom:private','name':'Private','storage_key':'packages/private-v1','entry':'SKILL.md',
            'tools':['skill_resource'],'max_calls':4,'max_turns':6,'max_output_tokens':1024,'timeout_s':120,'max_budget_usd':.1}
    async def main():
        await engine.start();await engine.submit('e'*32,'custom:private',body(skill_policy=policy,workspace_key='a'*32))
        async for _ in engine.events('e'*32):pass
        await engine.close()
    asyncio.run(main())
    args=list(capture['args']);mcp=json.loads(args[args.index('--mcp-config')+1])
    env=mcp['mcpServers']['research']['env']
    assert env['RESEARCH_SKILL_ROOT']==str(own)
    assert env['RESEARCH_DB_PATH']==str(runtime.parent/'app.db')
    assert env['RESEARCH_WORKSPACE']=='a'*32
    assert 'Account-private skill instructions' in args[args.index('--system-prompt')+1]


def test_budget_stop_preserves_partial_output(engine,monkeypatch):
    lines=[json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'partial findings'}]}}),result_line('',subtype='error_max_budget_usd',is_error=True)]
    monkeypatch.setattr(jobs_mod.asyncio,'create_subprocess_exec',make_spawn(lines))
    async def main():
        await engine.start()
        await engine.submit('e'*32,'chat',body())
        frames=[f async for f in engine.events('e'*32)]
        r=frames[-1]['result']
        assert r['status']=='failed' and r['answer']=='partial findings'
        assert r['metadata']['finish_reason']=='budget_usd' and r['metadata']['partial_answer']
        await engine.close()
    asyncio.run(main())


def test_visible_text_arrives_before_cli_completion(engine, runtime, monkeypatch):
    delta = json.dumps({'type':'stream_event','event':{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'Visible draft'}}})
    monkeypatch.setattr(jobs_mod.asyncio, 'create_subprocess_exec', make_spawn([delta,result_line('Final answer')],delays={1:0.3}))
    async def main():
        await engine.start()
        ident='f'*32
        await engine.submit(ident,'chat',body())
        partial=None
        async for frame in engine.events(ident):
            if frame['type']=='progress' and frame.get('event',{}).get('answer'):
                partial=frame['event']['answer']
                assert engine.get(ident)['status']=='running'
            if frame['type']=='result':break
        assert partial=='Visible draft'
        await engine.close()
    asyncio.run(main())
