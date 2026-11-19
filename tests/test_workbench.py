"""Workspace state, source-aware drafts, image protocol and translation removal."""
import asyncio,io,json,sqlite3,uuid
from pathlib import Path
import pytest
import struct,zlib
from fastapi.testclient import TestClient
from app.schedules.router import router as schedules_router
from app.workbench.router import router as workbench_router
from app.storage import files as storage_files
from test_reader_imports import reading
from test_agent_mvp import client,wait

@pytest.fixture
def desk(reading):
    c,s,sid,ctx=reading;c.app.include_router(schedules_router);c.app.include_router(workbench_router)
    return c,s,sid,ctx

def png():
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',32,32,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0'*32)*32))+chunk(b'IEND',b'')

def test_workspace_restores_tabs_and_layout(desk):
    c,s,sid,ctx=desk;ident='a'*32
    body={'tabs':[{'paper_id':1,'session_id':sid}],'active_paper_id':1,'view':'read','layout':{'left_width':300,'right_width':380,'left_hidden':False,'right_hidden':True}}
    assert c.put('/api/workbench/states/'+ident,json=body).status_code==200
    saved=c.get('/api/workbench/states/'+ident).json();assert saved['tabs']==body['tabs'] and saved['layout']==body['layout']
    assert c.put('/api/workbench/states/'+ident,json={**body,'tabs':body['tabs']*2}).status_code==400
    assert c.put('/api/workbench/states/'+ident,json={**body,'active_paper_id':2}).status_code==400
    assert c.get('/api/workbench/states/../../secret').status_code==404

def test_reader_draft_context_and_images_survive_reopen(desk):
    c,s,sid,ctx=desk
    upload=c.post('/api/workbench/images',data={'conversation_id':sid,'paper_id':1},files={'file':('figure.png',png(),'image/png')});assert upload.status_code==201,upload.text
    image=upload.json();assert c.get(image['url']).headers['content-type']=='image/png'
    body={'prompt':'Explain this figure','contexts':[ctx],'attachment_ids':[image['id']]}
    assert c.put(f'/api/workbench/drafts/{sid}/1',json=body).status_code==200
    result=c.get(f'/api/workbench/drafts/{sid}/1').json();assert result['prompt']==body['prompt'] and result['contexts'][0]['paper_id']==ctx['paper_id'] and result['attachments'][0]['id']==image['id']
    assert c.put(f'/api/workbench/drafts/{sid}/1',json={'prompt':'Bad','contexts':[{**ctx,'paper_id':2}]}).status_code==400
    run=c.post('/api/agent/runs',json={'conversation_id':sid,'prompt':'Explain','attachment_ids':[image['id']],'request_key':'image-scope'}).json()
    assert wait(c,run['id'])['attachment_ids']==[image['id']]
    assert c.post('/api/agent/runs',json={'conversation_id':sid,'prompt':'Explain','request_key':'image-scope'}).status_code==409
    assert c.get(f'/api/workbench/drafts/{sid}/2').status_code==400

def test_image_validation_and_cross_session_scope(desk):
    c,s,sid,ctx=desk
    bad=c.post('/api/workbench/images',data={'conversation_id':sid,'paper_id':1},files={'file':('fake.png',b'not image')});assert bad.status_code==400
    assert c.post('/api/workbench/images',data={'conversation_id':sid,'paper_id':2},files={'file':('x.png',png())}).status_code==400
    a=c.post('/api/workbench/images',data={'conversation_id':sid,'paper_id':1},files={'file':('x.png',png())}).json()
    other=c.post('/api/sessions',json={'template_id':'read','paper_ids':[1]}).json()['session']['id']
    assert c.post('/api/agent/runs',json={'conversation_id':other,'prompt':'x','attachment_ids':[a['id']]}).status_code==400
    assert c.get('/api/workbench/images/no-such-file').status_code==404

def test_failed_translation_can_be_deleted_restored_and_retried(desk):
    c,s,sid,ctx=desk
    result=c.post('/api/reader/translations',json={**ctx,'conversation_id':sid}).json();wait(c,result['run_id'])
    with sqlite3.connect(s.db_path) as db:db.execute("UPDATE agent_runs SET status='failed',error='test source failure' WHERE id=?",(result['run_id'],))
    assert c.get('/api/reader/papers/1/translations').json()['translations'][0]['status']=='failed'
    assert c.patch('/api/reader/translations/'+result['id'],json={'deleted':True}).status_code==200
    assert c.get('/api/reader/papers/1/translations').json()['translations']==[]
    c.patch('/api/reader/translations/'+result['id'],json={'deleted':False})
    retry=c.post('/api/reader/translations',json={**ctx,'conversation_id':sid}).json();assert retry['run_id']!=result['run_id']
    wait(c,retry['run_id']);assert c.get('/api/reader/papers/1/translations').json()['translations'][0]['deleted']==0

def test_schedule_paused_by_default_and_manual_execution(desk):
    c,s,sid,ctx=desk
    result=c.post('/api/workbench/schedules',json={'title':'Daily reading','conversation_id':sid,'prompt':'Read','interval_hours':24});assert result.status_code==201
    item=result.json();assert item['enabled']==0
    r=c.post(f"/api/workbench/schedules/{item['id']}/run").json();assert wait(c,r['id'])['status']=='succeeded'
    assert c.get('/api/workbench/schedules').json()['schedules'][0]['last_run_id']==r['id']
    assert c.patch(f"/api/workbench/schedules/{item['id']}",json={'enabled':True}).status_code==200
    assert c.post('/api/workbench/schedules',json={'title':'Bad','conversation_id':999,'prompt':'x'}).status_code==404

def test_runner_native_image_stream_preserves_session_scope(desk,monkeypatch,tmp_path):
    from agent_runner import server
    c,s,sid,ctx=desk
    image=c.post('/api/workbench/images',data={'conversation_id':sid,'paper_id':1},files={'file':('x.png',png())}).json()
    native=c.get('/api/sessions/'+str(sid)).json()['session']['native_session_id']
    monkeypatch.setattr(server,'ROOT',tmp_path)
    (tmp_path/'data').symlink_to(s.data_dir,target_is_directory=True)
    (tmp_path/'skills'/'chat').mkdir(parents=True);(tmp_path/'skills'/'chat'/'SKILL.md').write_text('Discuss')
    monkeypatch.setattr(server,'RUNTIME',s.data_dir/'agent')
    monkeypatch.setattr(server,'load_environment',lambda:{})
    captured={}
    from test_agent_mvp import stream_proc
    async def spawn(*args,**kw):
        captured['args']=args
        proc=stream_proc([json.dumps({'type':'result','subtype':'success','result':'Red square','usage':{}})])
        captured['proc']=proc
        return proc
    monkeypatch.setattr(server.asyncio,'create_subprocess_exec',spawn)
    with TestClient(server.app) as rc:
        sub=rc.post('/runs',json={'run_id':'c'*32,'skill':'chat','prompt':'Describe','session_id':native,'paper_ids':[1],'attachment_ids':[image['id']]})
        assert sub.status_code==202,sub.text
        import time as _t
        for _ in range(200):
            got=rc.get('/runs/'+'c'*32).json()
            if got['status'] in ('succeeded','failed','cancelled'):break
            _t.sleep(0.01)
        result=got['result']
    captured['message']=json.loads(captured['proc'].stdin.data)
    assert result['status']=='succeeded',result
    assert '--input-format' in captured['args'] and '--verbose' in captured['args']
    assert captured['args'][captured['args'].index('--output-format')+1]=='stream-json'
    block=captured['message']['message']['content'][1];assert block['type']=='image' and block['source']['media_type']=='image/png'
    assert len(block['source']['data'])>50

def test_container_images_are_owned_by_host_runner_user(desk,monkeypatch):
    c,s,sid,ctx=desk;owners=[]
    monkeypatch.setattr(storage_files.os,'geteuid',lambda:0)
    monkeypatch.setattr(storage_files.os,'chown',lambda path,uid,gid:owners.append((Path(path),uid,gid)))
    response=c.post('/api/workbench/images',data={'conversation_id':sid,'paper_id':1},files={'file':('figure.png',png())})
    assert response.status_code==201
    owner=s.data_dir.stat();assert len(owners)==2
    assert all(uid==owner.st_uid and gid==owner.st_gid for _,uid,gid in owners)
    assert (s.data_dir/'attachments'/response.json()['id']).stat().st_mode&0o777==0o600

def test_runner_follows_existing_model_configuration(monkeypatch):
    from agent_runner import server
    monkeypatch.delenv('RESEARCH_AGENT_MODEL',raising=False)
    monkeypatch.delenv('RESEARCH_AGENT_VISION_MODEL',raising=False)
    assert server.current_model({'ANTHROPIC_MODEL':'configured-agent-model'})=='configured-agent-model'
    monkeypatch.setenv('RESEARCH_AGENT_VISION_MODEL','configured-vision-model')
    assert server.current_model({'ANTHROPIC_MODEL':'configured-agent-model'},vision=True)=='configured-vision-model'

def test_schedule_cannot_repeat_reading_without_fulltext(desk):
    c,s,sid,ctx=desk
    missing=c.post('/api/sessions',json={'template_id':'read','paper_ids':[2]}).json()['session']['id']
    result=c.post('/api/workbench/schedules',json={'title':'Missing PDF','conversation_id':missing,'prompt':'Read'})
    assert result.status_code==400 and 'PDF' in result.json()['detail']
