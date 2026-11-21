"""Custom connections use fake credentials and a fake CLI. No provider requests."""
import asyncio
import json
import socket
from pathlib import Path
import pytest
import httpx
from app.runner_config import connections
from app.runner_config.connection_schemas import ConnectionWrite,ConnectionRef,ConnectionDefault
from app.core.errors import ServiceError
from app.core.config import Settings
from app.core.db import get_conn
from app.agent import runner_client
from app.agent.protocol import RUNNER_PROTOCOL_VERSION
from agent_runner import connections as rc,jobs as jobs_mod,cli,server
from test_auth_accounts import secured,login,user
from test_agent_mvp import client,wait,runner_mock,CANNED_RESULT
from test_runner_jobs import engine,runtime,make_spawn,result_line,body

FAKE='test-only-never-real-key-123'
CONFIG={'base_url':'https://api.example.com/anthropic','model':'custom-model[1M]','vision':'declared_yes','context_window':1000000,'auth_type':'bearer','role_prompt':'Explain evidence carefully.'}

def write(**kw):return ConnectionWrite(name='own',config=CONFIG,api_key=FAKE,**kw)

def test_encrypted_storage_and_binding(tmp_path):
    settings=Settings(data_dir=tmp_path,qdrant_url='unused');db=get_conn(settings)
    c=connections.save(db,settings,write());ident=c['id'];ref=ConnectionRef(id=ident,revision=1)
    assert FAKE not in json.dumps(c)
    row=db.execute('SELECT * FROM runner_connections').fetchone();assert FAKE not in row['secret_cipher']
    assert connections.materialize(db,settings,connections.snapshot(db,settings,ref))==FAKE
    assert (tmp_path/'auth/runner-master.key').stat().st_mode&0o777==0o600
    bound=json.dumps(connections.snapshot(db,settings,ref))
    assert connections.snapshot(db,settings,None,bound)['model']==CONFIG['model']
    rc.check_current(tmp_path/'agent',{k:v for k,v in json.loads(bound).items() if k!='mode'})
    with pytest.raises(ServiceError):connections.snapshot(db,settings,ref,'{"mode":"legacy"}')
    connections.save(db,settings,ConnectionWrite(name='off',config=CONFIG,enabled=False,expected_revision=1),ident)
    with pytest.raises(ServiceError):connections.materialize(db,settings,json.loads(bound))
    with pytest.raises(ServiceError):connections.save(db,settings,ConnectionWrite(name='stale',config=CONFIG,expected_revision=1),ident)
    assert FAKE not in write().model_dump_json()
    db.close()

def test_web_isolation_validation_and_no_host_fallback(secured):
    c,app=secured;a=login(c)
    made=c.post('/api/me/runner/connections',headers=a,json={'name':'admin','config':CONFIG,'api_key':FAKE});assert made.status_code==201,made.text
    assert FAKE not in made.text
    other,account,a=user(c,app)
    assert c.get('/api/me/runner/connections',headers=other).json()['connections']==[]
    denied=c.post('/api/agent/runs',headers=other,json={'prompt':'no host key'})
    assert denied.status_code==409
    assert c.post('/api/me/runner/connections/preflight',headers=other,json={'connection':{'id':made.json()['id'],'revision':1}}).status_code==409
    bad=c.post('/api/me/runner/connections',headers=other,json={'name':'bad','config':{'base_url':'https://user:pass@host','model':'test'},'api_key':{'value':FAKE}})
    assert bad.status_code==422 and FAKE not in bad.text and 'user:pass' not in bad.text
    assert c.get('/api/me/runner/connections').status_code==401

def test_environment_has_only_selected_auth_and_explicit_model(tmp_path,monkeypatch):
    monkeypatch.setattr(rc,'validate_destination',lambda u:None)
    monkeypatch.setenv('ANTHROPIC_API_KEY','host-key');monkeypatch.setenv('RESEARCH_AGENT_MODEL','wrong-host-model')
    snap=CONFIG|{'id':'a'*32,'revision':1,'name':'own'}
    env=rc.environment(tmp_path,snap,FAKE)
    assert env['ANTHROPIC_AUTH_TOKEN']==FAKE and 'ANTHROPIC_API_KEY' not in env
    assert env['ANTHROPIC_MODEL']==CONFIG['model']
    assert 'connections' in env['CLAUDE_CONFIG_DIR']
    assert 'wrong-host-model' not in str(env)
    assert rc.redact({'a':[FAKE]},FAKE)=={'a':['[REDACTED]']}
    with pytest.raises(ValueError):rc.environment(tmp_path,snap,'')

@pytest.mark.parametrize('url',['http://api.example.com','https://127.0.0.1','https://localhost'])
def test_private_destination_blocked(monkeypatch,url):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):rc.validate_destination(url)

def test_custom_run_forwarding_and_session_binding(client,monkeypatch):
    c,settings=client;db=get_conn(settings);saved=connections.save(db,settings,write());db.close()
    captured=[];base=runner_mock(CANNED_RESULT,capture=captured)
    async def handler(req):
        if req.url.path=='/health':return httpx.Response(200,json={'status':'ok','protocol_version':RUNNER_PROTOCOL_VERSION})
        return await base(req)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
    inp={'prompt':'hello','connection':{'id':saved['id'],'revision':1}}
    first=c.post('/api/agent/runs',json=inp);assert first.status_code==202,first.text
    done=wait(c,first.json()['id']);assert done['status']=='succeeded'
    assert captured[0]['connection_secret']==FAKE and captured[0]['connection_snapshot']['model']==CONFIG['model']
    assert FAKE not in json.dumps(done)
    follow=c.post('/api/agent/runs',json={'prompt':'follow','conversation_id':done['conversation_id']})
    assert follow.status_code==202,follow.text
    assert wait(c,follow.json()['id'])['diagnostics']['connection_snapshot']['id']==saved['id']
    db=get_conn(settings);another=connections.save(db,settings,write());db.close()
    assert c.post('/api/agent/runs',json={'prompt':'change endpoint','conversation_id':done['conversation_id'],'connection':{'id':another['id'],'revision':1}}).status_code==409

def test_runner_uses_custom_env_and_scrubs_events(engine,runtime,monkeypatch):
    snap=CONFIG|{'id':'a'*32,'revision':1,'name':'own'}
    monkeypatch.setattr(rc,'check_current',lambda *a:None);monkeypatch.setattr(rc,'validate_destination',lambda *a:None)
    monkeypatch.setattr(engine,'_env_loader',lambda *a:(_ for _ in ()).throw(AssertionError('must not load host config')))
    cap={};lines=[json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':FAKE}]}}),result_line('done '+FAKE)]
    monkeypatch.setattr(jobs_mod.asyncio,'create_subprocess_exec',make_spawn(lines,capture=cap))
    async def main():
        await engine.start();await engine.submit('b'*32,'chat',body(connection_snapshot=snap,_connection_secret=FAKE))
        frames=[f async for f in engine.events('b'*32)]
        assert frames[-1]['result']['status']=='succeeded'
        assert FAKE not in json.dumps(frames)
        assert '_connection_secret' not in engine._jobs['b'*32]['body']
        assert cap['kwargs']['env']['ANTHROPIC_AUTH_TOKEN']==FAKE
        args=cap['args'];assert args[args.index('--model')+1]==CONFIG['model']
        assert CONFIG['role_prompt'] in args[args.index('--system-prompt')+1]
        assert not any(FAKE in p.read_text() for p in (runtime/'runs').rglob('*.json*'))
        await engine.close()
    asyncio.run(main())


def test_mcp_subprocess_receives_no_model_credentials(tmp_path):
    import os,subprocess
    script=tmp_path/'tool.py'
    script.write_text("import os,json; print(json.dumps({k:k in os.environ for k in ['ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_CUSTOM_HEADERS','CLAUDE_CODE_OAUTH_TOKEN','RESEARCH_RUN_ID']}))")
    cmd=rc.mcp_command(script)
    env={**os.environ,'ANTHROPIC_API_KEY':FAKE,'ANTHROPIC_AUTH_TOKEN':FAKE,'ANTHROPIC_CUSTOM_HEADERS':FAKE,'CLAUDE_CODE_OAUTH_TOKEN':FAKE,'RESEARCH_RUN_ID':'test'}
    out=subprocess.run([cmd['command'],*cmd['args']],env=env,capture_output=True,text=True,check=True)
    assert json.loads(out.stdout)=={'ANTHROPIC_API_KEY':False,'ANTHROPIC_AUTH_TOKEN':False,'ANTHROPIC_CUSTOM_HEADERS':False,'CLAUDE_CODE_OAUTH_TOKEN':False,'RESEARCH_RUN_ID':True}
