"""Reader/import contracts tested with isolated SQLite and no paid model."""
import asyncio
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import pymupdf
import pytest
from app.imports.router import router as imports_router, internal as imports_internal
from app.reader import router as reader_router
from app.reader.pages import pdf_file
from app.imports import sources as paper_sources, pipeline as import_service
from app.core.db import get_conn
from test_agent_mvp import client,wait

@pytest.fixture
def reading(client,sample_pdf):
    c,s=client
    c.app.include_router(reader_router);c.app.include_router(imports_router);c.app.include_router(imports_internal)
    (s.data_dir/'papers').mkdir();path=s.data_dir/'papers'/'1.pdf';shutil.copyfile(sample_pdf,path)
    with sqlite3.connect(s.db_path) as db:
        db.execute('INSERT INTO papers(id,title,pdf_path,authors) VALUES (1,?,?,?)',('Sample',str(path),'["A"]'))
        db.execute("INSERT INTO papers(id,title) VALUES (2,'Metadata only')")
    sid=c.post('/api/sessions',json={'template_id':'read','paper_ids':[1]}).json()['session']['id']
    info=c.get('/api/reader/papers/1').json()
    ctx={'paper_id':1,'page':1,'file_version':info['file_version'],'quote':'Research assistants need to read papers quickly.','rects':[[.1,.1,.3,.03]]}
    return c,s,sid,ctx

def test_document_and_physical_page_range(reading):
    c,s,sid,ctx=reading
    info=c.get('/api/reader/papers/1').json();assert info['page_count']==2
    assert any(t['page']==2 for t in info['outline'])
    page=c.get('/api/reader/papers/1/pages/2').json();assert page['page']==2 and '2 Method' in page['text'] and page['text_source']=='original_pdf_page'
    r=c.get('/api/reader/papers/1/file',headers={'Range':'bytes=0-7'});assert r.status_code==206 and r.content.startswith(b'%PDF-')
    assert c.get('/api/reader/papers/1/pages/3').status_code==400
    assert c.get('/api/reader/papers/2').status_code==400
    assert c.get('/api/reader/papers/999').status_code==404

def test_annotation_geometry_persistence_delete_undo(reading):
    c,s,sid,ctx=reading
    r=c.post('/api/reader/annotations',json={**ctx,'conversation_id':sid,'kind':'highlight'});assert r.status_code==201,r.text
    a=r.json();assert a['validation']=='text_located'
    assert len(c.get('/api/reader/papers/1/annotations').json()['annotations'])==1
    c.patch('/api/reader/annotations/'+a['id'],json={'deleted':True})
    assert not c.get('/api/reader/papers/1/annotations').json()['annotations']
    c.patch('/api/reader/annotations/'+a['id'],json={'deleted':False})
    assert c.get('/api/reader/papers/1/annotations').json()['annotations'][0]['rects']==ctx['rects']

@pytest.mark.parametrize('change',[{'page':9},{'file_version':'0'*64},{'paper_id':2}])
def test_stale_or_missing_evidence_rejected(reading,change):
    c,s,sid,ctx=reading
    r=c.post('/api/reader/annotations',json={**ctx,**change,'kind':'highlight'});assert r.status_code==409

@pytest.mark.parametrize('change',[{'rects':[[.8,.1,.4,.1]]},{'rects':[]},{'quote':''},{'page':0}])
def test_invalid_highlight_input(reading,change):
    c,s,sid,ctx=reading
    assert c.post('/api/reader/annotations',json={**ctx,**change}).status_code==422

def test_notes_ink_and_position(reading):
    c,s,sid,ctx=reading
    note=c.post('/api/reader/annotations',json={**ctx,'kind':'note','content':'My observation'});assert note.status_code==201
    assert c.patch('/api/reader/annotations/'+note.json()['id'],json={'content':''}).status_code==400
    assert c.post('/api/reader/annotations',json={**ctx,'kind':'ink','quote':'','points':[[.1,.1],[.2,.3]]}).status_code==201
    pos={'conversation_id':sid,'page':2,'zoom':'1.25','tab':'notes'}
    assert c.put('/api/reader/papers/1/state',json=pos).status_code==200
    assert c.get('/api/reader/papers/1/state',params={'conversation_id':sid}).json()['page']==2
    assert c.put('/api/reader/papers/1/state',json={**pos,'page':3}).status_code==400
    assert c.get('/api/reader/papers/2/state',params={'conversation_id':sid}).status_code==400

def test_translation_cache_avoids_second_run(reading):
    c,s,sid,ctx=reading
    body={**ctx,'conversation_id':sid}
    one=c.post('/api/reader/translations',json=body);assert one.status_code==200,one.text
    run=wait(c,one.json()['run_id']);assert run['contexts'][0]['page']==1 and run['purpose']=='translate'
    two=c.post('/api/reader/translations',json=body).json();assert two['cached'] and two['run_id']==run['id']
    assert len(c.get('/api/agent/runs').json()['runs'])==1

def test_run_context_scope_and_idempotency(reading):
    c,s,sid,ctx=reading
    b={'conversation_id':sid,'prompt':'Explain','contexts':[ctx],'request_key':'ctx1'}
    run=c.post('/api/agent/runs',json=b).json();wait(c,run['id'])
    assert c.post('/api/agent/runs',json=b).json()['id']==run['id']
    assert c.post('/api/agent/runs',json={**b,'contexts':[{**ctx,'file_version':'0'*64}]}).status_code==409
    assert c.post('/api/agent/runs',json={**b,'request_key':'ctx2','contexts':[{**ctx,'paper_id':2}]}).status_code==409

def test_upload_validation_and_internal_scope(reading):
    c,s,sid,ctx=reading
    assert c.post('/api/imports/upload',data={'request_key':'bad'},files={'file':('bad.pdf',b'not pdf')}).status_code==400
    file=(s.data_dir/'papers'/'1.pdf').read_bytes()
    r=c.post('/api/imports/upload',data={'request_key':'upload1'},files={'file':('../../x.pdf',file,'application/pdf')});assert r.status_code==202,r.text
    item=r.json();assert item['original_filename']=='x.pdf'
    assert c.post('/api/imports/upload',data={'request_key':'upload1'},files={'file':('x.pdf',file)}).json()['id']==item['id']
    endpoint='/api/internal/imports/'+item['id']+'/execute'
    assert c.post(endpoint).status_code==403
    folder=s.data_dir/'agent';folder.mkdir(exist_ok=True);(folder/'internal-token').write_text('private-test-token')
    assert c.post(endpoint,headers={'X-Research-Tool-Token':'wrong'}).status_code==403
    wait(c,item['run_id'])
    with sqlite3.connect(s.db_path) as db:db.execute("UPDATE agent_runs SET status='running' WHERE id=?",(item['run_id'],))
    c.app.state.embedder=None;c.app.state.store=None
    result=c.post(endpoint,headers={'X-Research-Tool-Token':'private-test-token','X-Research-Run-Id':item['run_id']});assert result.status_code==200,result.text
    assert result.json()['paper_id']==1
    assert c.get('/api/imports/'+item['id']).json()['status']=='completed'
    assert not (s.data_dir/'imports'/(item['id']+'.pdf')).exists()

@pytest.mark.parametrize('url',['http://example.com/x.pdf','https://127.0.0.1/a.pdf','https://169.254.169.254/x','https://u:p@example.com/a','https://example.com:8600/a'])
def test_import_rejects_private_or_unsafe_urls(reading,url):
    c,*_=reading
    assert c.post('/api/imports/source',json={'value':url,'channel':'url'}).status_code==400

def test_doi_metadata_only_and_idempotence(reading,monkeypatch):
    c,s,sid,ctx=reading
    async def metadata(value):return {'title':'Verified title','doi':'10.1234/test','authors':['Author'],'abstract':'Metadata','affiliations':[]}
    monkeypatch.setattr(import_service,'doi_metadata',metadata)
    db=get_conn(s)
    db.execute("INSERT INTO import_requests(id,request_key,channel,source_value) VALUES ('doi1','doi1','doi','10.1234/test')");db.commit()
    row=db.execute("SELECT * FROM import_requests WHERE id='doi1'").fetchone()
    result=asyncio.run(import_service.process_import(row,db,s,None,None));assert not result['has_pdf']
    again=asyncio.run(import_service.process_import(row,db,s,None,None));assert again['paper_id']==result['paper_id']
    assert db.execute('SELECT pdf_path FROM papers WHERE id=?',(result['paper_id'],)).fetchone()[0] is None
    db.close()

def test_file_scope_blocks_path_escape(reading,tmp_path):
    c,s,sid,ctx=reading
    outside=tmp_path.parent/'outside.pdf';outside.write_bytes(b'%PDF-1.7')
    with pytest.raises(ValueError):pdf_file(s,{'pdf_path':str(outside)})

def test_public_url_checks_all_addresses(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('10.0.0.1',443))])
    with pytest.raises(ValueError):asyncio.run(paper_sources.public_url('https://mixed.example/file.pdf'))

def test_mcp_advertises_only_selected_skill_tools(monkeypatch):
    import os,subprocess,sys
    script=Path(__file__).resolve().parents[1]/'agent_runner/tools.py'
    env={**os.environ,'RESEARCH_ALLOWED_TOOLS':'["paper_import"]'}
    req={'jsonrpc':'2.0','id':1,'method':'tools/list'}
    result=subprocess.run([sys.executable,str(script)],input=json.dumps(req)+'\n',capture_output=True,text=True,check=True,env=env)
    assert [t['name'] for t in json.loads(result.stdout)['result']['tools']]==['paper_import']

def test_upload_creates_index_and_resumes_reserved_row(reading):
    c,s,sid,ctx=reading
    import numpy as np
    class Embedder:
        def embed(self,texts):return [[.1,.2] for _ in texts]
    class Store:
        points=[]
        def delete_paper(self,pid):pass
        def upsert_chunks(self,points):self.points.extend(points)
    store=Store();folder=s.data_dir/'imports';folder.mkdir(exist_ok=True)
    # Keep original bytes independent from an existing file's fingerprint.
    doc=pymupdf.open(s.data_dir/'papers'/'1.pdf');doc.set_metadata({'title':'Another indexed paper'});doc.save(folder/'fresh.pdf');doc.close()
    db=get_conn(s)
    db.execute("INSERT INTO import_requests(id,request_key,channel,source_value,original_filename) VALUES ('fresh','fresh','upload','uploaded_pdf','fresh.pdf')");db.commit()
    result=asyncio.run(import_service.process_import(db.execute("SELECT * FROM import_requests WHERE id='fresh'").fetchone(),db,s,Embedder(),store))
    assert result['has_pdf'] and result['paper_id'] not in (1,2)
    assert store.points and db.execute('SELECT count(*) FROM chunks_meta WHERE paper_id=?',(result['paper_id'],)).fetchone()[0]==len(store.points)
    assert (s.data_dir/'papers'/f"{result['paper_id']}.pdf").exists()
    db.close()

def test_arxiv_metadata_html_fallback_requires_matching_identity():
    text='<meta name="citation_arxiv_id" content="1706.03762"><meta name="citation_title" content="Attention Is All You Need"><meta name="citation_author" content="Ashish Vaswani"><meta name="citation_abstract" content="Transformer">'
    result=paper_sources.parse_arxiv_html(text,'1706.03762')
    assert result['title']=='Attention Is All You Need' and result['abstract']=='Transformer'
    with pytest.raises(ValueError):paper_sources.parse_arxiv_html(text,'2401.00001')

def test_upload_idempotency_rejects_changed_content(reading):
    c,s,sid,ctx=reading
    file=(s.data_dir/'papers'/'1.pdf').read_bytes()
    first=c.post('/api/imports/upload',data={'request_key':'conflict'},files={'file':('x.pdf',file)});assert first.status_code==202
    assert c.post('/api/imports/upload',data={'request_key':'conflict'},files={'file':('x.pdf',file+b'changed')}).status_code==409

def test_scanned_pdf_reports_missing_text(tmp_path):
    path=tmp_path/'scan.pdf';d=pymupdf.open();d.new_page();d.save(path);d.close()
    with pytest.raises(ValueError,match='文字层'):import_service.pdf_metadata(path,'scan.pdf')

def test_full_queue_keeps_import_visible_and_retryable(reading,monkeypatch):
    from fastapi import HTTPException
    from app.agent import service as agent
    c,s,sid,ctx=reading
    async def full(*a,**kw):raise HTTPException(429,'Queue full; please wait')
    monkeypatch.setattr(agent,'create_run',full)
    r=c.post('/api/imports/source',json={'value':'10.1234/test','channel':'doi','request_key':'queue-full'})
    assert r.status_code==202 and r.json()['status']=='failed'
    assert r.json()['conversation_id'] and r.json()['run_id'] is None
    assert 'Queue full' in c.get('/api/imports/'+r.json()['id']).json()['error']

def test_page_tool_reads_physical_page_and_enforces_session(reading,monkeypatch):
    from agent_runner.tools import paper_page
    c,s,sid,ctx=reading
    monkeypatch.setenv('RESEARCH_PAPER_IDS','[1]')
    result=paper_page(1,2,str(s.db_path))
    assert result['page']==2 and result['text_source']=='original_pdf_page' and '2 Method' in result['text']
    with pytest.raises(ValueError,match='linked'):paper_page(2,1,str(s.db_path))

def test_pdf_redirect_cannot_reach_private_network(monkeypatch):
    import httpx
    visited=[];checked=[]
    async def public(url):
        checked.append(url)
        if '127.0.0.1' in url:raise ValueError('private redirect')
        return url
    def handler(request):
        visited.append(str(request.url));return httpx.Response(302,headers={'Location':'https://127.0.0.1/secret.pdf'})
    cls=httpx.AsyncClient
    monkeypatch.setattr(paper_sources,'public_url',public)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:cls(transport=httpx.MockTransport(handler),**kwargs))
    with pytest.raises(ValueError,match='private redirect'):asyncio.run(paper_sources.fetch_pdf('https://public.example/p.pdf'))
    assert len(visited)==1 and len(checked)==2

def test_known_arxiv_is_reused_without_network(reading,monkeypatch):
    c,s,sid,ctx=reading
    async def forbidden(*a):raise AssertionError('Known paper must not use network')
    monkeypatch.setattr(import_service,'arxiv_metadata',forbidden)
    monkeypatch.setattr(import_service,'fetch_pdf',forbidden)
    db=get_conn(s)
    db.execute("UPDATE papers SET arxiv_id='2303.04137' WHERE id=1")
    db.execute("INSERT INTO import_requests(id,request_key,channel,source_value) VALUES ('existing','existing','arxiv','2303.04137')");db.commit()
    result=asyncio.run(import_service.process_import(db.execute("SELECT * FROM import_requests WHERE id='existing'").fetchone(),db,s,None,None))
    assert result['paper_id']==1 and result['has_pdf']
    db.close()

def test_old_upload_reuses_verified_arxiv_watermark_without_network(reading,monkeypatch):
    c,s,sid,ctx=reading
    path=s.data_dir/'papers'/'1.pdf';doc=pymupdf.open(path)
    doc[0].insert_text((15,350),'arXiv:2303.04137v4 [cs.RO] 1 Jun 2023',fontsize=8,rotate=90);doc.saveIncr();doc.close()
    async def forbidden(*a):raise AssertionError('Verified local watermark must avoid network')
    monkeypatch.setattr(import_service,'arxiv_metadata',forbidden)
    db=get_conn(s)
    db.execute("INSERT INTO import_requests(id,request_key,channel,source_value) VALUES ('watermark','watermark','arxiv','2303.04137')");db.commit()
    result=asyncio.run(import_service.process_import(db.execute("SELECT * FROM import_requests WHERE id='watermark'").fetchone(),db,s,None,None))
    assert result['paper_id']==1 and db.execute('SELECT arxiv_id FROM papers WHERE id=1').fetchone()[0]=='2303.04137'
    db.close()

def test_translation_cache_separates_same_quote_on_different_pages(reading):
    c,s,sid,ctx=reading
    first=c.post('/api/reader/translations',json={**ctx,'quote':'the','conversation_id':sid}).json();wait(c,first['run_id'])
    second=c.post('/api/reader/translations',json={**ctx,'page':2,'quote':'the','conversation_id':sid}).json()
    assert not second['cached'] and second['run_id']!=first['run_id']

def test_upload_duplicate_key_oversized_still_413(reading):
    from app.imports.service import MAX_PDF_BYTES
    c,s,sid,ctx=reading
    file=(s.data_dir/'papers'/'1.pdf').read_bytes()
    assert c.post('/api/imports/upload',data={'request_key':'big-dup'},files={'file':('x.pdf',file)}).status_code==202
    big=b'%PDF-1.4'+b'\0'*MAX_PDF_BYTES
    assert c.post('/api/imports/upload',data={'request_key':'big-dup'},files={'file':('x.pdf',big)}).status_code==413

def test_upload_oversized_invalid_pdf_reports_magic_400(reading):
    from app.imports.service import MAX_PDF_BYTES
    c,s,sid,ctx=reading
    big=b'not pdf'+b'\0'*MAX_PDF_BYTES
    r=c.post('/api/imports/upload',data={'request_key':'big-bad'},files={'file':('x.pdf',big)})
    assert r.status_code==400 and '有效 PDF' in r.json()['detail']
