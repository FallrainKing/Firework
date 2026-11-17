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

from app.api import agent, sessions, library
from app.config import Settings
from app.db import get_conn
from agent_runner.tools import library_search

@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, qdrant_url=':memory:')
    async def handler(request):
        if request.url.path == '/health':
            return httpx.Response(200, json={'status':'ok','model':'test-model','skills':[]})
        return httpx.Response(200, json={'status':'succeeded','answer':'Saved answer: diffusion policy','model':'test-model','usage':{'input_tokens':12,'output_tokens':5},'cli_estimated_cost_usd':0.001,'tool_calls':[],'metadata':{}})
    monkeypatch.setattr(agent, 'client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://test'))
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings
        app.state.db = get_conn(settings)
        agent.init_agent_state(app)
        yield
        await agent.close_agent_state(app)
        app.state.db.close()
    app = FastAPI(lifespan=lifespan)
    app.include_router(agent.router)
    app.include_router(sessions.router)
    app.include_router(library.router)
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
    monkeypatch.setattr(agent,'client',lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
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
    def handler(req):
        captured.append(json.loads(req.content))
        return httpx.Response(200,json={'status':'succeeded','answer':'followup'})
    monkeypatch.setattr(agent,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
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
    assert len(replies[1]['result']['tools'])==3
    assert replies[2]['error']['code']==-32601

def test_tool_permissions_do_not_allow_arbitrary_execution():
    script=Path(__file__).resolve().parents[1]/'agent_runner/tools.py'
    req={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'shell','arguments':{'query':'id'}}}
    result=subprocess.run([sys.executable,str(script)],input=json.dumps(req)+'\n',capture_output=True,text=True,check=True)
    assert 'not allowed' in json.loads(result.stdout)['error']['message']

def test_runner_rejects_search_without_real_tool_success(monkeypatch,tmp_path):
    from agent_runner import server
    class Proc:
        returncode=0
        async def communicate(self,_):
            return json.dumps({'subtype':'success','result':'invented result','usage':{'input_tokens':10}}).encode(),b''
    async def spawn(*args,**kwargs):
        assert '--restricted' in args and '--bare' in args
        assert '--tools' in args and args[args.index('--tools')+1]==''
        return Proc()
    monkeypatch.setattr(server,'RUNTIME',tmp_path)
    monkeypatch.setattr(server,'load_environment',lambda:{})
    monkeypatch.setattr(server.asyncio,'create_subprocess_exec',spawn)
    with TestClient(server.app) as c:
        r=c.post('/run',json={'run_id':'a'*32,'skill':'search_library','prompt':'search'})
    assert r.status_code==200
    assert r.json()['status']=='failed'
    assert r.json()['usage']['input_tokens']==10

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
