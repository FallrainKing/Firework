"""Version migration, PDF exports and index switching; no research-model calls."""
import hashlib
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
import pytest
from qdrant_client import QdrantClient

from app.documents.router import router
from app.documents import service
from app.documents.export import annotated_pdf
from app.rag.vector_store import VectorStore, ChunkPoint
from test_agent_mvp import client
from test_reader_imports import reading


@pytest.fixture
def documents(reading):
    c,s,sid,ctx=reading
    c.app.include_router(router)
    store=VectorStore(QdrantClient(':memory:'))
    store.ensure_collection(4)
    c.app.state.store=store
    c.app.state.embedder=SimpleNamespace(embed=lambda texts:[[1.,0.,0.,0.] for _ in texts])
    yield c,s,sid,ctx
    store._client.close()


def pdf(text='New revision', rotation=0):
    with pymupdf.open() as d:
        p=d.new_page(width=400,height=600)
        p.insert_text((40,70),text)
        p.set_rotation(rotation)
        return d.tobytes()


def listing(c,pid=1):
    r=c.get(f'/api/library/papers/{pid}/documents');assert r.status_code==200,r.text
    return r.json()


def upload(c,data=None,pid=1,**fields):
    return c.post(f'/api/library/papers/{pid}/document-versions',data={'label':'v2',**fields},files={'file':('revision.pdf',data or pdf(),'application/pdf')})


def test_legacy_registration_preserves_paper_and_annotation_identity(documents):
    c,s,sid,ctx=documents
    a=c.post('/api/reader/annotations',json={**ctx,'conversation_id':sid,'kind':'highlight'}).json()
    before=(s.data_dir/'papers/1.pdf').read_bytes()
    first=listing(c);second=listing(c)
    assert first==second
    vid=first['default_version_id'];v=first['documents'][0]['versions'][0]
    assert v['file_hash']==ctx['file_version'] and v['annotation_count']==1
    row=c.app.state.db.execute('SELECT * FROM reader_annotations WHERE id=?',(a['id'],)).fetchone()
    assert row['document_version_id']==vid and row['id']==a['id']
    assert (s.data_dir/'papers/1.pdf').read_bytes()==before
    assert c.app.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0


def test_dedup_versions_and_supplement_not_default(documents):
    c,s,*_=documents
    old=listing(c)['default_version_id']
    raw=pdf()
    v=upload(c,raw).json()['version_id']
    again=upload(c,raw).json()
    assert again=={'version_id':v,'deduplicated':True}
    supp=upload(c,pdf('Appendix'),role='supplement',title='Appendix').json()['version_id']
    data=listing(c)
    assert len(data['documents'])==2 and data['default_version_id']==old
    assert len(list((s.data_dir/'papers').glob('blob-*.pdf')))==3
    r=c.post(f'/api/library/papers/1/document-versions/{supp}/default',json={'confirmed':True,'expected_version_id':old})
    assert r.status_code==400


def test_switch_reindexes_preserves_old_file_and_blocks_old_native_context(documents):
    c,s,sid,ctx=documents
    old=listing(c)['default_version_id']
    new=upload(c,pdf('Fresh version content')).json()['version_id']
    r=c.post(f'/api/library/papers/1/document-versions/{new}/default',json={'confirmed':True,'expected_version_id':old})
    assert r.status_code==200,r.text
    assert listing(c)['default_version_id']==new
    assert c.get('/api/reader/papers/1').json()['file_version']!=ctx['file_version']
    assert 'Fresh version' in c.app.state.db.execute('SELECT text FROM chunks_meta WHERE paper_id=1').fetchone()[0]
    assert c.get(f'/api/library/papers/1/document-versions/{old}/file').status_code==200
    stale=c.post('/api/agent/runs',json={'conversation_id':sid,'prompt':'Continue','request_key':'old-file'})
    assert stale.status_code==409 and '旧 PDF' in stale.json()['detail']
    fresh=c.post('/api/sessions',json={'template_id':'read','paper_ids':[1]}).json()['session']['id']
    r=c.post('/api/agent/runs',json={'conversation_id':fresh,'prompt':'New file','request_key':'new-file'})
    assert r.status_code==202,r.text


def test_default_confirmation_and_compare_and_swap(documents):
    c,*_=documents
    old=listing(c)['default_version_id'];new=upload(c).json()['version_id']
    url=f'/api/library/papers/1/document-versions/{new}/default'
    assert c.post(url,json={'confirmed':False,'expected_version_id':old}).status_code==422
    assert c.post(url,json={'confirmed':True,'expected_version_id':'obsolete'}).status_code==409
    assert listing(c)['default_version_id']==old


def test_failed_index_keeps_default_and_vectors(documents):
    c,*_=documents
    old=listing(c)['default_version_id'];new=upload(c).json()['version_id']
    store=c.app.state.store
    store.upsert_chunks([ChunkPoint(1,0,'Old search material',1,'body',[1.,0.,0.,0.])])
    with patch.object(store,'upsert_chunks',side_effect=RuntimeError('index unavailable')):
        with pytest.raises(RuntimeError):
            c.post(f'/api/library/papers/1/document-versions/{new}/default',json={'confirmed':True,'expected_version_id':old})
    assert listing(c)['default_version_id']==old
    assert store.search([1.,0.,0.,0.],paper_id=1)[0].text=='Old search material'


def test_export_current_version_only_and_no_original_mutation(documents):
    c,s,sid,ctx=documents
    old=listing(c)['default_version_id'];original=(s.data_dir/'papers/1.pdf').read_bytes()
    a=c.post('/api/reader/annotations',json={**ctx,'conversation_id':sid,'kind':'highlight','content':'中文解释：这是重点。'}).json()
    c.post('/api/reader/annotations',json={**ctx,'kind':'ink','quote':'','points':[[.2,.3],[.3,.4]]})
    hidden=c.post('/api/reader/annotations',json={**ctx,'kind':'note','content':'Must be absent'}).json()
    c.patch('/api/reader/annotations/'+hidden['id'],json={'deleted':True})
    new=upload(c).json()['version_id']
    base=f'/api/library/papers/1/document-versions/{old}/file'
    r=c.get(base+'?mode=annotated')
    assert r.status_code==200 and 'attachment' in r.headers['content-disposition']
    with pymupdf.open(stream=r.content,filetype='pdf') as doc:
        anns=list(doc[0].annots());assert len(anns)==2
        assert '中文解释' in anns[0].info['content']
    empty=c.get(f'/api/library/papers/1/document-versions/{new}/file?mode=annotated')
    with pymupdf.open(stream=empty.content,filetype='pdf') as doc:assert not list(doc[0].annots())
    assert (s.data_dir/'papers/1.pdf').read_bytes()==original
    assert c.get(base).content==original
    assert '中文解释' in c.get(base+'?mode=markdown').text


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_rotated_annotation_coordinates_and_native_annotations(rotation,tmp_path):
    raw=pdf(rotation=rotation)
    with pymupdf.open(stream=raw,filetype='pdf') as d:
        d[0].add_text_annot((20,20),'Existing PDF note')
        raw=d.tobytes()
    path=tmp_path/'rotated.pdf';path.write_bytes(raw)
    item={'page':1,'kind':'highlight','color':'#f5d76e','origin':'user','content':'Test','quote':'','rects':[[.1,.2,.3,.05]],'points':[]}
    result=annotated_pdf(path,[item])
    with pymupdf.open(stream=result,filetype='pdf') as d:
        page=d[0];anns=list(page.annots());assert len(anns)==2
        assert anns[0].info['content']=='Existing PDF note'
        pts=[pymupdf.Point(p)*page.rotation_matrix for p in anns[1].vertices]
        assert min(p.x for p in pts)/page.rect.width==pytest.approx(.1,abs=.001)
        assert min(p.y for p in pts)/page.rect.height==pytest.approx(.2,abs=.001)
        assert max(p.x for p in pts)/page.rect.width==pytest.approx(.4,abs=.001)


def test_unavailable_historical_hash_and_cross_paper_ids(documents):
    c,s,sid,ctx=documents
    vid=listing(c)['default_version_id']
    assert c.get(f'/api/library/papers/2/document-versions/{vid}/file').status_code==404
    assert c.get(f'/api/library/papers/2/document-versions/{vid}/annotations').status_code==404
    db=c.app.state.db
    db.execute("INSERT INTO reader_annotations(id,paper_id,file_version,page,kind,content) VALUES ('unresolved',1,?,1,'note','Historical')",('0'*64,));db.commit()
    data=listing(c)
    assert data['unresolved_annotations']==[{'file_hash':'0'*64,'count':1}]
    row=db.execute('SELECT document_version_id FROM reader_annotations WHERE id=\'unresolved\'').fetchone()
    assert row[0] is None


def test_invalid_upload_and_missing_asset_are_explicit(documents):
    c,s,*_=documents
    assert upload(c,b'not a PDF').status_code==400
    assert upload(c,pid=999).status_code==404
    vid=listing(c)['default_version_id']
    row=service.version(c.app.state.db,1,vid)
    (s.data_dir/'papers'/row['storage_key']).unlink()
    assert c.get(f'/api/library/papers/1/document-versions/{vid}/file').status_code==404


def test_export_origin_filters_and_inactive_ai_are_excluded(documents):
    c,s,sid,ctx=documents
    vid=listing(c)['default_version_id'];db=c.app.state.db
    for ident,origin in [('manual','user'),('adopted','ai_adopted'),('generated','ai'),('inactive','ai')]:
        db.execute('INSERT INTO reader_annotations(id,paper_id,file_version,page,kind,content,origin) VALUES (?,1,?,1,\'note\',?,?)',(ident,ctx['file_version'],ident,origin))
    db.execute("INSERT INTO reader_guide_tasks(id,paper_id,file_version,semantic_key,request_key,request_json,skill_id,manifest_id,status,active) VALUES ('guide',1,?,'key','request','{}','paper_guide','manifest','published',1)",(ctx['file_version'],))
    db.execute("UPDATE reader_annotations SET guide_task_id='guide' WHERE id='generated'");db.commit()
    base=f'/api/library/papers/1/document-versions/{vid}/annotations'
    assert {a['id'] for a in c.get(base).json()['annotations']}=={'manual','adopted','generated'}
    assert {a['id'] for a in c.get(base+'?origin=personal').json()['annotations']}=={'manual','adopted'}
    assert [a['id'] for a in c.get(base+'?origin=ai').json()['annotations']]==['generated']


from test_auth_accounts import secured, login, user


def test_new_document_routes_enforce_account_and_anonymous_isolation(secured):
    c,app=secured
    admin=login(c)
    root=app.state.settings.data_dir/'papers';root.mkdir()
    path=root/'1.pdf';path.write_bytes(pdf())
    app.state.db.execute("INSERT INTO papers(id,title,pdf_path) VALUES (1,'Private paper',?)",(str(path),));app.state.db.commit()
    data=c.get('/api/library/papers/1/documents',headers=admin).json()
    vid=data['default_version_id']
    export=f'/api/library/papers/1/document-versions/{vid}/file?mode=annotated'
    assert c.get(export,headers=admin).status_code==200
    assert c.get(export).status_code==401
    other,account,admin=user(c,app)
    assert c.get(export,headers=other).status_code==404
    assert c.get('/api/library/papers/1/documents',headers=other).status_code==404
    assert c.get(f'/api/library/papers/1/document-versions/{vid}/annotations',headers=other).status_code==404
    assert c.post(f'/api/library/papers/1/document-versions/{vid}/default',headers=other,json={'confirmed':True,'expected_version_id':vid}).status_code==404


def test_sql_failure_restores_old_index_and_default(documents):
    c,s,sid,ctx=documents
    old=listing(c)['default_version_id'];new=upload(c).json()['version_id']
    db=c.app.state.db;store=c.app.state.store
    store.upsert_chunks([ChunkPoint(1,0,'Old index',1,'body',[1.,0.,0.,0.])])
    db.execute("CREATE TRIGGER reject_default BEFORE UPDATE OF default_version_id ON papers WHEN NEW.default_version_id<>OLD.default_version_id BEGIN SELECT RAISE(ABORT,'test failure'); END");db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        c.post(f'/api/library/papers/1/document-versions/{new}/default',json={'confirmed':True,'expected_version_id':old})
    assert listing(c)['default_version_id']==old
    assert store.search([1.,0.,0.,0.],paper_id=1)[0].text=='Old index'


def test_running_tasks_prevent_default_switch_and_switch_blocks_new_runs(documents):
    c,s,sid,ctx=documents
    old=listing(c)['default_version_id'];new=upload(c).json()['version_id'];db=c.app.state.db
    db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status) VALUES ('active','active',?,'paper_read','test','running')",(sid,));db.commit()
    r=c.post(f'/api/library/papers/1/document-versions/{new}/default',json={'confirmed':True,'expected_version_id':old})
    assert r.status_code==409 and listing(c)['default_version_id']==old
    db.execute("UPDATE agent_runs SET status='succeeded' WHERE id='active'");db.commit()
    c.app.state.document_switches={1}
    r=c.post('/api/agent/runs',json={'conversation_id':sid,'prompt':'Race','request_key':'race'})
    assert r.status_code==409
    assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==1


def test_reader_loads_historical_pdf_and_keeps_positions_per_version(documents):
    c,s,sid,ctx=documents
    old=listing(c)['default_version_id'];new=upload(c,pdf('A different PDF')).json()['version_id']
    assert c.post(f'/api/library/papers/1/document-versions/{new}/default',json={'confirmed':True,'expected_version_id':old}).status_code==200
    historical=c.get('/api/reader/papers/1',params={'version_id':old}).json()
    assert historical['file_version']==ctx['file_version'] and historical['document_version_id']==old
    assert c.get(historical['pdf_url']).content==(s.data_dir/'papers/1.pdf').read_bytes()
    r=c.put('/api/reader/papers/1/state',json={'conversation_id':sid,'file_version':ctx['file_version'],'page':1,'zoom':'1.25','tab':'notes'})
    assert r.status_code==200,r.text
    assert c.get('/api/reader/papers/1/state',params={'conversation_id':sid,'file_version':ctx['file_version']}).json()['zoom']=='1.25'
    assert c.get('/api/reader/papers/1/state',params={'conversation_id':sid}).json()['zoom']=='fit'
    assert c.get('/api/reader/papers/2',params={'version_id':old}).status_code==404


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_anchor_resolves_rotated_text_and_reports_ambiguity(documents,rotation):
    c,s,sid,ctx=documents
    vid=upload(c,pdf('Unique source quote',rotation=rotation)).json()['version_id']
    digest=service.version(c.app.state.db,1,vid)['file_hash']
    r=c.post('/api/reader/anchors/locate',json={'paper_id':1,'file_version':digest,'page':1,'quote':'Unique source quote','rects':[]})
    assert r.status_code==200,r.text
    a=r.json();assert a['status']=='located' and a['document_version_id']==vid
    assert all(0<=n<=1 for rect in a['rects'] for n in rect)
    assert c.post('/api/reader/anchors/locate',json={'paper_id':1,'file_version':digest,'page':2,'quote':'Unique source quote'}).status_code==422
    raw=pdf('Repeat phrase Repeat phrase');v2=upload(c,raw).json()['version_id'];h2=service.version(c.app.state.db,1,v2)['file_hash']
    ambiguous=c.post('/api/reader/anchors/locate',json={'paper_id':1,'file_version':h2,'page':1,'quote':'Repeat phrase'}).json()
    assert ambiguous['status']=='ambiguous' and ambiguous['rects']==[]
