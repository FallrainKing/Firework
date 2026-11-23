import json
import uuid
from pathlib import Path
import httpx
import pytest
from fastapi import HTTPException
from app.core.config import Settings
from app.core.db import get_conn
from app.sessions.service import create_session
from app.sessions.schemas import SessionCreate
from agent_runner.native import transcript
from app.agent import runner_client
from test_auth_accounts import secured,login,user


def setup(tmp_path,custom=False):
    db=get_conn(Settings(data_dir=tmp_path,qdrant_url='unused'))
    from app.agent.repository import seed_templates
    from app.agent.catalog import TEMPLATES
    seed_templates(db,TEMPLATES)
    session=create_session(db,SessionCreate())['session']
    runtime=tmp_path/'agent';runtime.mkdir()
    if custom:
        snap={'mode':'custom','id':'a'*32,'revision':2}
        db.execute('UPDATE conversations SET runner_connection_json=? WHERE id=?',(json.dumps(snap),session['id']));db.commit()
        config=runtime/'connections'/('a'*32+'-2')/'claude-config'
    else:config=runtime/'claude-config'
    folder=config/'projects'/'project';folder.mkdir(parents=True)
    file=folder/(session['native_session_id']+'.jsonl')
    return db,runtime,session,file


def record(sid,role='assistant',**kw):
    return {'type':role,'sessionId':sid,'uuid':str(uuid.uuid4()),'message':{'content':[{'type':'text','text':'Visible text'}]},**kw}


def write(file,rows):file.write_text(''.join(json.dumps(r)+'\n' for r in rows))


def test_cursor_history_excludes_thinking_tools_payload_and_other_sessions(tmp_path):
    db,rt,s,f=setup(tmp_path,True);sid=s['native_session_id']
    rows=[record(sid,'user'),record(sid,message={'content':[{'type':'thinking','thinking':'private-thought'},{'type':'tool_use','name':'paper_read','input':{'key':'private-tool-input'}},{'type':'image','source':{'data':'private-base64'}}]}),record(str(uuid.uuid4())),record(sid,isSidechain=True),record(sid)]
    write(f,rows)
    first=transcript(rt,s['id'],limit=1);assert first['has_more'] and len(first['events'])==1
    second=transcript(rt,s['id'],first['next_offset'],first['source'])
    assert len(second['events'])==2 and second['events'][0]['tools']==['paper_read']
    assert second['events'][0]['images']==1
    assert not any(x in json.dumps(second) for x in ('private-thought','private-tool-input','private-base64'))
    with pytest.raises(HTTPException):transcript(rt,s['id'],3,first['source'])
    with pytest.raises(HTTPException):transcript(rt,s['id'],first['next_offset'])
    db.close()


def test_partial_record_waits_and_replaced_file_resets(tmp_path):
    db,rt,s,f=setup(tmp_path,True);sid=s['native_session_id']
    line=json.dumps(record(sid));f.write_text(line)
    one=transcript(rt,s['id']);assert one['events']==[] and one['next_offset']==0
    f.write_text(line+'\n');two=transcript(rt,s['id']);assert len(two['events'])==1
    old=f.with_suffix('.old');f.rename(old);write(f,[record(sid)])
    reset=transcript(rt,s['id'],two['next_offset'],two['source']);assert reset['reset'] and len(reset['events'])==1
    db.close()


def test_symlink_collision_and_no_global_fallback(tmp_path):
    db,rt,s,f=setup(tmp_path);sid=s['native_session_id']
    write(f,[record(sid)])
    with pytest.raises(HTTPException):transcript(rt,s['id'])
    assert transcript(rt,s['id'],allow_legacy=True)['events']
    target=f.parent/'other';target.write_text(f.read_text());f.unlink();f.symlink_to(target)
    with pytest.raises(HTTPException):transcript(rt,s['id'],allow_legacy=True)
    f.unlink();write(f,[record(sid)])
    duplicate=f.parent.parent/'another';duplicate.mkdir();write(duplicate/f.name,[record(sid)])
    with pytest.raises(HTTPException):transcript(rt,s['id'],allow_legacy=True)
    db.close()


def test_web_history_is_account_bound_and_redacts_credentials(secured,monkeypatch):
    c,app=secured;a=login(c)
    key='test-native-key-never-real'
    config={'base_url':'https://api.example.com','model':'test'}
    r=c.post('/api/me/runner/connections',headers=a,json={'name':'own','config':config,'api_key':key});assert r.status_code==201
    s=c.post('/api/sessions',headers=a,json={'template_id':'chat'}).json()['session']
    calls=[]
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,json={'session_id':s['native_session_id'],'state':'available','events':[{'text':key,'tools':[key]}],'next_offset':20,'source':'a'*32,'has_more':False,'reset':False})
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://runner'))
    r=c.get(f"/api/sessions/{s['id']}/native",headers=a);assert r.status_code==200,r.text
    assert key not in r.text and '[REDACTED]' in r.text
    other,_,_=user(c,app)
    count=len(calls)
    assert c.get(f"/api/sessions/{s['id']}/native",headers=other).status_code==404
    assert len(calls)==count
    assert c.get(f"/api/sessions/{s['id']}/native").status_code==401
    assert app.state.db.execute('select count(*) from agent_runs').fetchone()[0]==0


def test_provider_probe_has_no_model_credentials_or_model_requests(tmp_path,monkeypatch):
    import asyncio
    from agent_runner import native
    executable=tmp_path/'.local/bin/claude';executable.parent.mkdir(parents=True);executable.touch()
    monkeypatch.setattr(native.Path,'home',lambda:tmp_path)
    monkeypatch.setattr(native,'_provider_cache',None)
    monkeypatch.setenv('ANTHROPIC_API_KEY','private-test-only')
    calls=[]
    class Proc:
        returncode=0
        def __init__(self,flag):self.flag=flag
        async def communicate(self):return (b'2.1.322 Claude Code' if self.flag=='--version' else b'--include-partial-messages --output-format stream-json'),b''
    async def spawn(*args,**kw):
        calls.append((args,kw));return Proc(args[-1])
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    r=asyncio.run(native.provider_status())
    assert r['version']=='2.1.322' and r['capabilities']['structured_stream']
    assert not r['capabilities']['terminal'] and r['authentication']=='not_checked'
    assert all(args[-1] in ('--version','--help') for args,kw in calls)
    assert all('ANTHROPIC_API_KEY' not in kw['env'] for args,kw in calls)
    assert asyncio.run(native.provider_status())==r and len(calls)==2


def test_private_runner_reads_only_owned_config_and_session(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from agent_runner import server
    db,rt,s,f=setup(tmp_path,True);write(f,[record(s['native_session_id'])])
    monkeypatch.setattr(server,'RUNTIME',rt)
    monkeypatch.setattr(server,'load_environment',lambda:{})
    with TestClient(server.app) as c:
        r=c.get(f"/native/sessions/{s['id']}")
        assert r.status_code==200,r.text
        assert len(r.json()['events'])==1
        assert c.get(f"/native/sessions/{s['id']+1}").status_code==404
    db.close()


def test_long_text_is_explicitly_marked_truncated():
    from agent_runner.native import visible
    sid=str(uuid.uuid4())
    event=visible(record(sid,message={'content':[{'type':'text','text':'x'*50000}]}),sid)
    assert len(event['text'])==48000 and event['truncated']
    assert visible(record(sid,message='malformed'),sid) is None
