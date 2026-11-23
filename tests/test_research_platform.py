"""Cross-milestone regressions: real SQLite/PDFs, no production data or model calls."""
import sqlite3
import pytest
from app.research.router import router
from app.documents.router import router as document_router
from test_reader_imports import reading
from test_agent_mvp import client,wait

@pytest.fixture
def research(reading):
    c,s,sid,ctx=reading
    c.app.include_router(router);c.app.include_router(document_router)
    return c,s,sid,ctx

def ok(r,status=200):
    assert r.status_code==status,r.text
    return r.json()

def artifact(c,**changes):
    return ok(c.post('/api/research/artifacts',json={'title':'Reading evidence','markdown':'Original interpretation','paper_ids':[1],'status':'complete',**changes}),201)

def test_knowledge_review_revision_and_recall(research):
    c,_,_,_=research;a=artifact(c)
    k=ok(c.post('/api/research/knowledge',json={'title':'Research finding','markdown':'Evidence-led finding','sources':[{'artifact_id':a['id'],'revision':1}],'claim_type':'inference'}),201)
    assert not ok(c.get('/api/research/knowledge/recall'))['knowledge']
    transition={'action':'publish','expected_revision':1,'expected_state':'candidate'}
    ok(c.post(f"/api/research/knowledge/{k['id']}/transition",json=transition))
    assert len(ok(c.get('/api/research/knowledge/recall'))['knowledge'])==1
    assert c.post(f"/api/research/knowledge/{k['id']}/transition",json=transition).status_code==409
    ok(c.patch(f"/api/research/artifacts/{a['id']}",json={'title':a['title'],'markdown':'Corrected finding','paper_ids':[1],'status':'complete','expected_revision':1}))
    assert not ok(c.get('/api/research/knowledge/recall'))['knowledge']
    assert ok(c.get(f"/api/research/knowledge/{k['id']}"))['needs_review']
    assert ok(c.get(f"/api/research/artifacts/{a['id']}?revision=1"))['markdown']=='Original interpretation'
    assert c.patch(f"/api/research/artifacts/{a['id']}",json={'title':'stale','markdown':'Overwrite','paper_ids':[1],'expected_revision':1}).status_code==409

def test_source_facts_require_verified_evidence(research):
    c,_,_,_=research;a=artifact(c)
    k=ok(c.post('/api/research/knowledge',json={'title':'Fact','markdown':'Unverified fact','sources':[{'artifact_id':a['id'],'revision':1}],'claim_type':'source'}),201)
    assert c.post(f"/api/research/knowledge/{k['id']}/transition",json={'action':'publish','expected_revision':1,'expected_state':'candidate'}).status_code==422

def test_asset_dedup_ownership_and_revision_retention(research):
    c,s,_,_=research
    f=ok(c.post('/api/research/files',data={'paper_id':1},files={'file':('evidence.md',b'# Evidence')}),201)
    again=ok(c.post('/api/research/files',data={'paper_id':1},files={'file':('same.md',b'# Evidence')}),201)
    assert f['hash']==again['hash']
    assert c.post('/api/research/files',data={'paper_id':2},files={'file':('same.md',b'# Evidence')}).status_code==409
    assert c.post('/api/research/files',data={'paper_id':1},files={'file':('bad.html',b'<script>1</script>')}).status_code==422
    a=artifact(c,file_ids=[f['hash']]);assert a['files'][0]['hash']==f['hash']
    r=c.get('/api/research/files/'+f['hash']);assert r.content==b'# Evidence' and 'attachment' in r.headers['content-disposition']
    path=s.data_dir/'research-files'/f['hash'];path.chmod(0o600);path.write_bytes(b'tampered')
    assert c.get('/api/research/files/'+f['hash']).status_code==409
    assert c.post('/api/research/files',data={'paper_id':1},files={'file':('evidence.md',b'# Evidence')}).status_code==409

def test_run_events_materials_artifact_and_debug_bundle(research):
    c,_,sid,_=research
    r=ok(c.post('/api/agent/runs',json={'conversation_id':sid,'prompt':'Read sample','request_key':'cross-milestone'}),202)
    result=wait(c,r['id']);assert result['status']=='succeeded'
    timeline=ok(c.get(f"/api/agent/runs/{r['id']}/timeline"))
    assert timeline['events'] and timeline['events'][-1]['kind']=='finished'
    mats=ok(c.get(f"/api/agent/runs/{r['id']}/materials"));assert mats['authorized'][0]['paper_id']==1
    saved=ok(c.get('/api/research/artifacts'))['artifacts'];assert any(a['source_run_id']==r['id'] for a in saved)
    assert c.get(f"/api/agent/runs/{r['id']}/debug-bundle").status_code==200
    assert c.get('/api/agent/runs/'+'f'*32+'/timeline').status_code==404

def test_fork_preview_and_confirm_are_model_free_and_idempotent(research):
    c,s,sid,_=research
    # Existing default connection may be legacy; preview never starts an execution.
    p=ok(c.post(f'/api/sessions/{sid}/fork-preview',json={'include_history':False}))
    body={'include_history':False,'confirmation_hash':p['confirmation_hash']}
    a=ok(c.post(f'/api/sessions/{sid}/forks',json=body),201)
    b=ok(c.post(f'/api/sessions/{sid}/forks',json=body),201)
    assert a['session']['id']==b['session']['id'] and not a['model_called']
    with sqlite3.connect(s.db_path) as db:assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0
    assert c.post(f'/api/sessions/{sid}/forks',json={**body,'confirmation_hash':'0'*64}).status_code==409
