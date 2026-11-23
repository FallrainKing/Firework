"""Agent MVP tests use no paid model requests and never touch production data."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.papers.router import router as library_router
from app.agent.router import router as agent_router
from app.agent import service as agent, runner_client
from app.sessions import router as sessions_router
from app.core.errors import register_error_handlers
from app.core.config import Settings
from app.core.db import get_conn
from agent_runner.tools import library_search

class _SSE(httpx.AsyncByteStream):
    def __init__(self, frames):
        self._data = ''.join(f'data: {json.dumps(f, ensure_ascii=False)}\n\n' for f in frames).encode()
    async def __aiter__(self):
        yield self._data


class _HangingSSE(httpx.AsyncByteStream):
    """Progress frame, then stays open until the client disconnects."""
    async def __aiter__(self):
        yield b'data: {"type":"progress","event":{"type":"assistant","text":"working"}}\n\n'
        await asyncio.Event().wait()


def runner_mock(result, capture=None, frames=None, hang=False):
    """Mock Runner speaking the async protocol. result: dict or fn(payload)->dict."""
    submitted = {}
    def resolve(run_id):
        payload = submitted.get(run_id, {})
        return result(payload) if callable(result) else result
    async def handler(request):
        path = request.url.path
        if path == '/health':
            return httpx.Response(200, json={'status':'ok','model':'test-model','skills':[],'concurrency':2,'queued':0,'running':0})
        if path == '/runs' and request.method == 'POST':
            payload = json.loads(request.content)
            submitted[payload['run_id']] = payload
            if capture is not None:
                capture.append(payload)
            return httpx.Response(202, json={'run_id':payload['run_id'],'status':'queued'})
        if path.endswith('/cancel'):
            run_id = path.split('/')[2]
            return httpx.Response(200, json={'run_id':run_id,'status':'cancelled'})
        if path.endswith('/events'):
            run_id = path.split('/')[2]
            if hang:
                return httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=_HangingSSE())
            fr = frames if frames is not None else [{'type':'progress','event':{'type':'assistant','text':'working'}},{'type':'result','result':resolve(run_id)}]
            return httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=_SSE(fr))
        if path.startswith('/runs/'):
            run_id = path.split('/')[2]
            res = resolve(run_id)
            return httpx.Response(200, json={'run_id':run_id,'status':res.get('status','succeeded'),'progress':None,'result':res})
        return httpx.Response(200, json=resolve(''))
    return handler


CANNED_RESULT = {'status':'succeeded','answer':'Saved answer: diffusion policy','model':'test-model','usage':{'input_tokens':12,'output_tokens':5},'cli_estimated_cost_usd':0.001,'tool_calls':[],'metadata':{}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, qdrant_url=':memory:')
    monkeypatch.setattr(runner_client,'client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(runner_mock(CANNED_RESULT)), base_url='http://test'))
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings
        app.state.db = get_conn(settings)
        agent.init_agent_state(app)
        yield
        await agent.close_agent_state(app)
        app.state.db.close()
    app = FastAPI(lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(agent_router)
    app.include_router(sessions_router)
    app.include_router(library_router)
    with TestClient(app) as c:
        yield c, settings

def wait(c, run_id):
    for _ in range(100):
        run = c.get('/api/agent/runs/' + run_id).json()
        if run['status'] in ('succeeded','failed'):
            return run
        time.sleep(0.01)
    pytest.fail('Task did not finish')

def test_agent_run_persists_usage_and_history_search(client):
    c,s = client
    r = c.post('/api/agent/runs', json={'prompt':'test prompt','request_key':'same'} )
    assert r.status_code == 202
    result = wait(c,r.json()['id'])
    assert result['status'] == 'succeeded'
    assert result['usage']['input_tokens'] == 12
    assert result['cost_verified'] is False
    assert c.get('/api/agent/runs?q=diffusion').json()['runs'][0]['id'] == result['id']
    with sqlite3.connect(s.db_path) as db:
        assert db.execute('select answer from agent_runs').fetchone()[0] == result['answer']

def test_idempotency_reuses_run_and_detects_conflicting_payload(client):
    c,_ = client
    body = {'prompt':'test','request_key':'key'}
    first = c.post('/api/agent/runs',json=body).json()
    wait(c,first['id'])
    second = c.post('/api/agent/runs',json=body).json()
    assert first['id'] == second['id']
    assert c.post('/api/agent/runs',json={**body,'prompt':'different'}).status_code == 409
    assert len(c.get('/api/agent/runs').json()['runs']) == 1

def test_validates_skill_prompt_and_conversation(client):
    c,_ = client
    assert c.post('/api/agent/runs',json={'prompt':'  '}).status_code == 400
    assert c.post('/api/agent/runs',json={'prompt':'x','skill':'shell'}).status_code == 400
    assert c.post('/api/agent/runs',json={'prompt':'x','conversation_id':999}).status_code == 404
    assert c.get('/api/agent/runs/missing').status_code == 404

def test_runner_failure_is_persisted_without_automatic_retry(client,monkeypatch):
    c,_ = client
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(runner_client,'client',lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
    r = c.post('/api/agent/runs',json={'prompt':'test'}).json()
    result = wait(c,r['id'])
    assert result['status'] == 'failed'
    assert result['usage'] == {}
    assert len(calls) == 1
    assert c.get('/api/agent/status').json()['runner']['status'] == 'offline'

def test_management_library_and_readonly_tool(client):
    c,s = client
    with sqlite3.connect(s.db_path) as db:
        db.execute("INSERT INTO papers(title,abstract,source) VALUES ('Diffusion Policy','robot learning','upload')")
        db.execute("INSERT INTO papers(title,abstract,source) VALUES ('Other','different','upload')")
    assert len(c.get('/api/agent/library?q=diffusion').json()['papers']) == 1
    assert len(library_search('',str(s.db_path))['papers']) == 2
    assert library_search('%',str(s.db_path))['papers'] == []
    assert library_search("' OR 1=1 --",str(s.db_path))['papers'] == []

def test_restart_marks_only_interrupted_runs(client):
    c,s = client
    result=wait(c,c.post('/api/agent/runs',json={'prompt':'finished'}).json()['id'])
    with sqlite3.connect(s.db_path) as db:
        db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status) VALUES ('stale','stale',?,'chat','interrupted','running')",(result['conversation_id'],))
    fake=SimpleNamespace(state=SimpleNamespace(db=get_conn(s)))
    agent.init_agent_state(fake)
    fake.state.db.close()
    assert c.get('/api/agent/runs/stale').json()['status']=='failed'
    assert c.get('/api/agent/runs/'+result['id']).json()['status']=='succeeded'

def test_followup_passes_bounded_saved_history(client,monkeypatch):
    c,_=client
    first=wait(c,c.post('/api/agent/runs',json={'prompt':'first'}).json()['id'])
    captured=[]
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(runner_mock({'status':'succeeded','answer':'followup'},capture=captured)),base_url='http://test'))
    wait(c,c.post('/api/agent/runs',json={'prompt':'second','conversation_id':first['conversation_id']}).json()['id'])
    assert captured[0]['history'][0]['content']=='first'
    assert captured[0]['history'][1]['role']=='assistant'

def test_mcp_transport_and_unknown_method():
    script=Path(__file__).resolve().parents[1]/'agent_runner/tools.py'
    data='\n'.join(json.dumps(x) for x in [{'jsonrpc':'2.0','id':1,'method':'initialize'},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'not-real'}])+'\n'
    result=subprocess.run([sys.executable,str(script)],input=data,capture_output=True,text=True,check=True)
    replies=[json.loads(x) for x in result.stdout.splitlines()]
    assert len(replies)==3
    assert replies[0]['result']['capabilities']['tools']=={}
    assert len(replies[1]['result']['tools'])==0
    assert replies[2]['error']['code']==-32601

def test_tool_permissions_do_not_allow_arbitrary_execution():
    script=Path(__file__).resolve().parents[1]/'agent_runner/tools.py'
    req={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'shell','arguments':{'query':'id'}}}
    result=subprocess.run([sys.executable,str(script)],input=json.dumps(req)+'\n',capture_output=True,text=True,check=True)
    assert 'not allowed' in json.loads(result.stdout)['error']['message']

def stream_proc(lines):
    """Streaming fake CLI process: stdout fed with stream-json lines."""
    import asyncio as _aio
    reader=_aio.StreamReader()
    for line in lines: reader.feed_data(line.encode()+b'\n')
    reader.feed_eof()
    class Stdin:
        data=b''
        def write(self,b): self.data+=b
        async def drain(self): pass
        def write_eof(self): pass
    class Proc:
        pid=4242
        returncode=0
        stdout=reader
        stderr=_aio.StreamReader()
        stdin=Stdin()
        async def wait(self): return 0
    return Proc()

def test_runner_rejects_search_without_real_tool_success(monkeypatch,tmp_path):
    from agent_runner import server
    async def spawn(*args,**kwargs):
        assert '--restricted' in args and '--bare' in args
        assert '--tools' in args and args[args.index('--tools')+1]==''
        return stream_proc([json.dumps({'type':'result','subtype':'success','result':'invented result','usage':{'input_tokens':10}})])
    monkeypatch.setattr(server,'RUNTIME',tmp_path)
    monkeypatch.setattr(server,'load_environment',lambda:{})
    monkeypatch.setattr(server.asyncio,'create_subprocess_exec',spawn)
    with TestClient(server.app) as c:
        r=c.post('/runs',json={'run_id':'a'*32,'skill':'search_library','prompt':'search'})
        assert r.status_code==202
        for _ in range(200):
            got=c.get('/runs/'+'a'*32).json()
            if got['status'] in ('succeeded','failed','cancelled'):break
            time.sleep(0.01)
        result=got['result']
    assert result['status']=='failed'
    assert result['usage']['input_tokens']==10

def test_arxiv_search_falls_back_without_extra_model_call(monkeypatch):
    from agent_runner import tools
    calls=[]
    monkeypatch.setattr(tools.time, 'sleep', lambda _: None)
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1234.56789</id><title>Real title</title><summary>Abstract</summary></entry></feed>'
    def urlopen(req,timeout):
        calls.append(req.full_url)
        if len(calls)==1:raise TimeoutError('upstream timeout')
        return Response()
    monkeypatch.setattr(tools.urllib.request,'urlopen',urlopen)
    result=tools.arxiv_search('"diffusion policy"')
    assert len(calls)==2
    assert 'arxiv.org/api/query?' in calls[1]
    assert 'sortBy' not in calls[0]
    assert result['papers'][0]['url']=='https://arxiv.org/abs/1234.56789'

def test_paper_search_crossref_uses_imports_sources(monkeypatch):
    from agent_runner import tools
    from app.imports import sources
    async def fake_crossref(query):
        return [{'title': 'Crossref paper', 'query': query}]
    monkeypatch.setattr(sources, 'crossref_search', fake_crossref)
    assert tools.paper_search('robotics', 'crossref') == [{'title': 'Crossref paper', 'query': 'robotics'}]

def test_skill_docs_cover_deep_reading():
    from pathlib import Path
    text = Path('skills/paper_read/SKILL.md').read_text()
    for kw in ('研究问题', '贡献边界', '覆盖范围', '证据', '作者陈述'):
        assert kw in text, kw


def test_services_are_framework_free():
    from pathlib import Path
    import app.imports.service as imports_service
    import app.schedules.service as schedules_service
    import app.workbench.service as workbench_service
    for m in (imports_service, schedules_service, workbench_service):
        assert 'fastapi' not in Path(m.__file__).read_text(), m.__name__


def test_catalog_budgets():
    from app.agent.catalog import SKILLS
    c = SKILLS['chat']
    assert (c['max_turns'], c['max_output_tokens'], c['timeout_s'], c['max_budget_usd']) == (6, 1024, 120, 0.10)
    for k in ('search_library', 'search_arxiv', 'paper_discover'):
        assert (SKILLS[k]['max_turns'], SKILLS[k]['max_output_tokens'], SKILLS[k]['timeout_s'], SKILLS[k]['max_budget_usd']) == (6, 1024, 120, 0.10)
    i = SKILLS['paper_import']
    assert (i['max_turns'], i['max_output_tokens'], i['timeout_s'], i['max_budget_usd']) == (6, 2048, 180, 0.20)
    for k in ('paper_read', 'paper_review', 'paper_compare'):
        r = SKILLS[k]
        assert (r['max_turns'], r['max_output_tokens'], r['timeout_s'], r['max_budget_usd']) == (30, 8192, None, 1.00)

def test_progress_persisted_during_run(client, monkeypatch):
    c,_ = client
    event = {'type':'assistant','tools':['paper_read'],'text':'reading page 2'}
    frames = [{'type':'progress','event':event},{'type':'result','result':CANNED_RESULT}]
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(runner_mock(CANNED_RESULT,frames=frames)),base_url='http://test'))
    run = wait(c, c.post('/api/agent/runs',json={'prompt':'read'}).json()['id'])
    assert run['status'] == 'succeeded'
    assert run['progress'] == event

def test_stream_break_marks_failed_no_retry(client, monkeypatch):
    c,_ = client
    submits = []
    base = runner_mock(CANNED_RESULT, capture=submits)
    async def handler(request):
        if request.url.path.endswith('/events'):
            raise httpx.ReadError('stream broke')
        return await base(request)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
    run = wait(c, c.post('/api/agent/runs',json={'prompt':'read'}).json()['id'])
    assert run['status'] == 'failed'
    assert 'No automatic retry' in run['error']
    assert len(submits) == 1

def test_cancel_running_run(client, monkeypatch):
    c,_ = client
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(runner_mock(CANNED_RESULT,hang=True)),base_url='http://test'))
    run = c.post('/api/agent/runs',json={'prompt':'long task'}).json()
    for _ in range(200):
        if c.get('/api/agent/runs/'+run['id']).json()['status'] == 'running':
            break
        time.sleep(0.01)
    r = c.post('/api/agent/runs/'+run['id']+'/cancel')
    assert r.status_code == 200 and r.json()['status'] == 'cancelled'
    # conversation is immediately free for a new run
    assert c.post('/api/agent/runs',json={'prompt':'next','conversation_id':run['conversation_id']}).status_code == 202

def test_cancel_finished_conflict(client):
    c,_ = client
    run = wait(c, c.post('/api/agent/runs',json={'prompt':'done'}).json()['id'])
    assert c.post('/api/agent/runs/'+run['id']+'/cancel').status_code == 409

def test_cancel_runner_offline_503(client, monkeypatch):
    c,_ = client
    base = runner_mock(CANNED_RESULT, hang=True)
    async def handler(request):
        if request.url.path.endswith('/cancel'):
            raise httpx.ConnectError('offline')
        return await base(request)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
    run = c.post('/api/agent/runs',json={'prompt':'long task'}).json()
    for _ in range(200):
        if c.get('/api/agent/runs/'+run['id']).json()['status'] == 'running':
            break
        time.sleep(0.01)
    r = c.post('/api/agent/runs/'+run['id']+'/cancel')
    assert r.status_code == 503
    assert c.get('/api/agent/runs/'+run['id']).json()['status'] == 'running'

def test_app_sse_emits_terminal(client):
    c,_ = client
    run = wait(c, c.post('/api/agent/runs',json={'prompt':'done'}).json()['id'])
    ev = c.get('/api/agent/runs/'+run['id']+'/events')
    assert ev.status_code == 200 and ev.headers['content-type'].startswith('text/event-stream')
    assert 'data: ' in ev.text and '"succeeded"' in ev.text
    assert c.get('/api/agent/runs/missing/events').status_code == 404

def _insert_queued_run(s, run_id, skill='chat'):
    from app.core.db import get_conn
    db = get_conn(s)
    db.execute("INSERT INTO conversations(module,title,messages,skill,kind,native_session_id) VALUES ('agent','t','[]',?,'chat',?)", (skill, '11111111-1111-1111-1111-111111111111'))
    sid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status) VALUES (?,?,?,?,?,'queued')", (run_id, 'k-'+run_id, sid, skill, 'p'))
    db.commit()
    return db, sid

def test_cancel_before_submit_never_bills(client, monkeypatch):
    c,s = client
    run_id = 'a'*32
    db,sid = _insert_queued_run(s, run_id)
    state = SimpleNamespace(settings=s, db=db, agent_jobs=set())
    base = runner_mock(CANNED_RESULT)
    async def not_found(request):
        if request.url.path.endswith('/cancel'):
            return httpx.Response(404)
        return await base(request)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(not_found),base_url='http://test'))
    asyncio.run(agent.cancel_run(db, run_id, state))
    assert db.execute('SELECT status FROM agent_runs WHERE id=?', (run_id,)).fetchone()[0] == 'cancelled'
    submits = []
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(runner_mock(CANNED_RESULT,capture=submits)),base_url='http://test'))
    asyncio.run(agent.execute_run(run_id, state))
    assert submits == []  # cancelled before submit: no runner job, no billing
    db.close()

def test_close_cancels_runner_jobs(client, monkeypatch):
    c,s = client
    run_id = 'b'*32
    db,sid = _insert_queued_run(s, run_id)
    cancels = []
    async def handler(request):
        if request.url.path.endswith('/cancel'):
            cancels.append(request.url.path)
            return httpx.Response(200, json={'run_id':run_id,'status':'cancelled'})
        return httpx.Response(200, json={'status':'ok'})
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
    fake = SimpleNamespace(state=SimpleNamespace(db=db, agent_jobs=set()))
    asyncio.run(agent.close_agent_state(fake))
    assert cancels == ['/runs/'+run_id+'/cancel']
    db.close()

def test_late_result_cannot_overwrite_cancel(client):
    c,s = client
    run_id = 'c'*32
    db,sid = _insert_queued_run(s, run_id)
    from app.agent import repository as repo
    repo.cancel_run(db, run_id)
    repo.finish_run(db, run_id, 'succeeded', 'late answer', None, '{}', '[]', '{}', None, None)
    db.commit()
    row = db.execute('SELECT status,answer FROM agent_runs WHERE id=?', (run_id,)).fetchone()
    assert row['status'] == 'cancelled' and row['answer'] == ''
    db.close()


def test_streamed_partial_answer_survives_runner_failure(client,monkeypatch):
    c,_=client
    frames=[{'type':'progress','event':{'type':'text_snapshot','answer':'Already generated text'}},{'type':'result','result':{'status':'failed','error':'Connection lost'}}]
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(runner_mock({},frames=frames)),base_url='http://test'))
    r=c.post('/api/agent/runs',json={'prompt':'test partial output'})
    assert r.status_code==202
    result=wait(c,r.json()['id'])
    assert result['status']=='failed' and result['answer']=='Already generated text'
