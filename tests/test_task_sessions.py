"""Session lifecycle, native ID mapping and paper-card management regressions."""
import json
import sqlite3
import uuid
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from test_agent_mvp import client,wait

def paper(settings,title='Example',path=None):
    with sqlite3.connect(settings.db_path) as db:
        c=db.execute("INSERT INTO papers(title,authors,abstract,source,pdf_path) VALUES (?,'[\"Author\"]','Original abstract','upload',?)",(title,str(path) if path else None))
        return c.lastrowid

def test_templates_and_draft_session_do_not_call_agent(client):
    c,s=client
    data=c.get('/api/sessions/templates').json()
    assert {'read','review','compare','discover','chat'}<=set(t['id'] for t in data['templates'])
    assert c.post('/api/sessions',json={'template_id':'read'}).status_code==400
    ident=paper(s)
    result=c.post('/api/sessions',json={'template_id':'read','paper_ids':[ident]}).json()
    session=result['session']
    assert session['kind']=='reading' and session['paper_ids']==[ident]
    uuid.UUID(session['native_session_id'])
    assert not session['native_ready'] and session['run_count']==0
    assert c.get('/api/agent/runs').json()['runs']==[]

def test_comparison_selection_and_invalid_materials(client):
    c,s=client;a=paper(s,'A');b=paper(s,'B')
    assert c.post('/api/sessions',json={'template_id':'compare','paper_ids':[a,a]}).status_code==400
    assert c.post('/api/sessions',json={'template_id':'compare','paper_ids':[a,999]}).status_code==400
    assert c.post('/api/sessions',json={'template_id':'compare','paper_ids':[a,b]}).status_code==201

def test_category_rename_archive_pin_and_search(client):
    c,s=client
    category=c.post('/api/sessions/categories',json={'name':'机器人'}).json()
    assert c.post('/api/sessions/categories',json={'name':'机器人'}).status_code==409
    session=c.post('/api/sessions',json={'template_id':'chat','category_id':category['id']}).json()['session']
    ident=session['id']
    assert c.patch(f'/api/sessions/{ident}',json={'title':'恢复任务','pinned':True}).status_code==200
    assert c.get('/api/sessions?q=恢复').json()['sessions'][0]['id']==ident
    assert len(c.get('/api/sessions?category_id='+str(category['id'])).json()['sessions'])==1
    c.patch(f'/api/sessions/{ident}',json={'archived':True})
    assert c.get('/api/sessions').json()['sessions']==[]
    assert c.get('/api/sessions?archived=true').json()['sessions'][0]['id']==ident
    assert c.post('/api/agent/runs',json={'conversation_id':ident,'prompt':'continue'}).status_code==409
    assert c.patch(f'/api/sessions/{ident}',json={'archived':False,'category_id':None}).status_code==200
    assert len(c.get('/api/sessions?category_id=0').json()['sessions'])==1

def test_fixed_skill_and_bound_paper_payload(client,monkeypatch):
    from app.agent import runner_client as agent
    c,s=client;pid=paper(s)
    session=c.post('/api/sessions',json={'template_id':'read','paper_ids':[pid]}).json()['session']
    assert c.post('/api/agent/runs',json={'conversation_id':session['id'],'skill':'chat','prompt':'x'}).status_code==409
    captures=[]
    from test_agent_mvp import runner_mock
    mock=runner_mock(lambda p:{'status':'succeeded','answer':'read','session_id':p['session_id'],'native_ready':True},capture=captures)
    monkeypatch.setattr(agent,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(mock),base_url='http://test'))
    first=wait(c,c.post('/api/agent/runs',json={'conversation_id':session['id'],'prompt':'read'}).json()['id'])
    second=wait(c,c.post('/api/agent/runs',json={'conversation_id':session['id'],'prompt':'continue'}).json()['id'])
    assert captures[0]['paper_ids']==[pid]
    assert captures[0]['session_id']==captures[1]['session_id']==session['native_session_id']
    assert captures[1]['native_ready'] and captures[1]['history']==[]
    assert c.get(f"/api/sessions/{session['id']}").json()['session']['native_ready']

def test_custom_template_is_persisted_and_extensible(client):
    c,s=client
    template=c.post('/api/sessions/templates',json={'name':'读方法','skill':'chat','prompt':'聚焦方法','description':'custom'}).json()
    assert template['builtin']==0
    session=c.post('/api/sessions',json={'template_id':template['id']}).json()
    assert session['session']['template_id']==template['id']
    assert session['starting_prompt']=='聚焦方法'
    assert c.post('/api/sessions/templates',json={'name':'bad','skill':'shell'}).status_code==400

def test_session_run_pagination_has_no_missing_turns(client):
    c,s=client
    sid=c.post('/api/sessions',json={'template_id':'chat'}).json()['session']['id']
    with sqlite3.connect(s.db_path) as db:
        for i in range(7):db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status) VALUES (?, ?,?,'chat',?,'succeeded')",(str(i),str(i),sid,str(i)))
    page=c.get(f'/api/sessions/{sid}/runs?limit=3').json()
    assert [r['prompt'] for r in page['runs']]==['4','5','6'] and page['has_more']
    older=c.get(f"/api/sessions/{sid}/runs?limit=3&before={page['next_before']}").json()
    assert [r['prompt'] for r in older['runs']]==['1','2','3']

def test_paper_cards_collections_metadata_and_optimistic_lock(client):
    c,s=client;pid=paper(s)
    collection=c.post('/api/library/collections',json={'name':'策略学习'}).json()
    card=c.get(f'/api/library/papers/{pid}').json()
    assert card['summary']=='Original abstract' and card['affiliations']==[] and card['authors']==['Author']
    update=c.patch(f'/api/library/papers/{pid}',json={'metadata_version':card['metadata_version'],'affiliations':['Actual University'],'brief_summary':'简要摘要','collection_ids':[collection['id']]}).json()
    assert update['affiliation_source']=='user' and update['collections'][0]['name']=='策略学习'
    assert c.patch(f'/api/library/papers/{pid}',json={'metadata_version':card['metadata_version'],'brief_summary':'stale'}).status_code==409
    assert c.get('/api/library/papers?q=Actual').json()['total']==1
    assert c.get('/api/library/papers?collection_id='+str(collection['id'])).json()['total']==1
    assert c.get('/api/library/papers?collection_id=0').json()['total']==0
    assert c.get(f'/api/library/papers/{pid}/thumbnail').status_code==404

def test_pdf_preview_and_affiliation_provenance(client):
    import pymupdf
    c,s=client
    folder=s.data_dir/'papers';folder.mkdir()
    path=folder/'1.pdf'
    doc=pymupdf.open();page=doc.new_page();page.insert_text((72,72),'Stanford University');doc.save(path);doc.close()
    pid=paper(s,path=path)
    response=c.get(f'/api/library/papers/{pid}/thumbnail')
    assert response.status_code==200 and response.content.startswith(b'\x89PNG')
    data=c.post(f'/api/library/papers/{pid}/refresh-card').json()
    assert data['affiliations']==['Stanford University'] and data['affiliation_source']=='pdf_first_page_unverified'
    c.patch(f'/api/library/papers/{pid}',json={'metadata_version':data['metadata_version'],'affiliations':['Confirmed University']})
    assert c.post(f'/api/library/papers/{pid}/refresh-card').json()['affiliations']==['Confirmed University']

def test_pdf_preview_rejects_paths_outside_papers(client,tmp_path):
    c,s=client;outside=tmp_path/'secret.pdf';outside.write_bytes(b'not-a-pdf');pid=paper(s,path=outside)
    assert c.get(f'/api/library/papers/{pid}/thumbnail').status_code==404

def test_paper_read_tool_enforces_session_scope_and_reports_coverage(client,monkeypatch):
    from agent_runner.tools import paper_read
    c,s=client;pid=paper(s)
    monkeypatch.setenv('RESEARCH_PAPER_IDS',json.dumps([pid]))
    with sqlite3.connect(s.db_path) as db:
        for i in range(10):db.execute('INSERT INTO chunks_meta(paper_id,chunk_idx,section,page,text) VALUES (?,?,?,?,?)',(pid,i,'Methods',1,'original evidence'))
    first=paper_read(pid,0,str(s.db_path))
    assert len(first['chunks'])==8 and first['has_more'] and not first['coverage']['figures_read']
    assert len(paper_read(pid,first['next_chunk_idx'],str(s.db_path))['chunks'])==2
    with pytest.raises(ValueError):paper_read(pid+1,0,str(s.db_path))

def test_native_missing_transcript_is_not_silently_replayed(monkeypatch,tmp_path):
    from agent_runner import server
    monkeypatch.setattr(server,'RUNTIME',tmp_path)
    with TestClient(server.app) as c:
        r=c.post('/runs',json={'run_id':'b'*32,'skill':'chat','prompt':'continue','session_id':str(uuid.uuid4()),'native_ready':True})
        assert r.status_code==202
        import time as _t
        for _ in range(200):
            got=c.get('/runs/'+'b'*32).json()
            if got['status'] in ('succeeded','failed','cancelled'):break
            _t.sleep(0.01)
        result=got['result']
    assert result['status']=='failed' and '原生会话文件缺失' in result['error']

def test_draft_prompt_survives_reopen_without_execution(client):
    c,s=client
    d=c.post('/api/sessions',json={'template_id':'chat','starting_prompt':'保存这个研究计划，稍后再执行'}).json()
    assert c.get('/api/sessions/'+str(d['session']['id'])).json()['session']['draft_prompt']=='保存这个研究计划，稍后再执行'
    assert c.get('/api/agent/runs').json()['runs']==[]

def test_native_resume_uses_same_workspace_and_session_id(monkeypatch,tmp_path):
    import asyncio
    from agent_runner import server, jobs
    from test_agent_mvp import stream_proc
    sid=str(uuid.uuid4());captured=[]
    async def spawn(*args,**kwargs):
        captured.append((args,kwargs))
        folder=tmp_path/'claude-config/projects/test';folder.mkdir(parents=True,exist_ok=True);(folder/(sid+'.jsonl')).write_text('native transcript')
        return stream_proc([json.dumps({'type':'result','subtype':'success','result':'ok','session_id':sid,'usage':{'input_tokens':5}})])
    monkeypatch.setattr(server,'RUNTIME',tmp_path)
    monkeypatch.setattr(server,'load_environment',lambda:{})
    monkeypatch.setattr(server.asyncio,'create_subprocess_exec',spawn)
    async def run_via_engine(eng,run_id,**kw):
        body={'prompt':kw.get('prompt','p'),'history':[],'session_id':kw.get('session_id'),'native_ready':kw.get('native_ready',False),'contexts':[],'attachment_ids':[],'paper_ids':[],'import_request_id':None}
        await eng.submit(run_id,'chat',body)
        await eng._jobs[run_id]['task']
        return eng.get(run_id)['result']
    async def probe():
        server.engine=jobs.JobEngine(tmp_path,concurrency=2,root=server.ROOT,env_loader=lambda rt:{})
        await server.engine.start()
        try:
            a=await run_via_engine(server.engine,'c'*32,session_id=sid,prompt='first')
            b=await run_via_engine(server.engine,'d'*32,session_id=sid,native_ready=True,prompt='next')
        finally:
            await server.engine.close()
        return a,b
    a,b=asyncio.run(probe())
    assert '--session-id' in captured[0][0] and '--resume' in captured[1][0]
    assert captured[0][1]['cwd']==captured[1][1]['cwd']
    assert a['session_id']==b['session_id']==sid and b['native_ready']
    assert b['metadata']['cost_scope']=='native_session_cumulative'

def test_affiliation_candidates_do_not_include_benchmark_or_copyright(client):
    import pymupdf
    from app.papers.assets import affiliation_candidates
    c,s=client
    folder=s.data_dir/'papers';folder.mkdir();path=folder/'2.pdf'
    doc=pymupdf.open();page=doc.new_page()
    for y,line in enumerate(['1Stanford University, 2Toyota Research Institute, 3MIT','simulated tasks across the Deepmind Control suite','Copyright Google DeepMind. All rights reserved']):page.insert_text((72,72+20*y),line)
    doc.save(path);doc.close()
    assert affiliation_candidates(s,path)==['Stanford University','Toyota Research Institute','MIT']

def test_collection_edit_does_not_silently_confirm_automatic_units(client):
    c,s=client;pid=paper(s)
    with sqlite3.connect(s.db_path) as db:db.execute("UPDATE papers SET affiliations='[\"University\"]',affiliation_source='pdf_first_page_unverified' WHERE id=?",(pid,))
    result=c.patch(f'/api/library/papers/{pid}',json={'metadata_version':1,'affiliations':['University'],'collection_ids':[]}).json()
    assert result['affiliation_source']=='pdf_first_page_unverified'
    result=c.patch(f'/api/library/papers/{pid}',json={'metadata_version':result['metadata_version'],'affiliations':['University'],'confirm_affiliations':True}).json()
    assert result['affiliation_source']=='user'
