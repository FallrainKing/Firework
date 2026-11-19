"""Skill guide contracts with isolated PDFs, real geometry and no model billing."""
import json,sqlite3
import httpx,pytest
from app.reader.guides.router import router,internal
from app.agent import runner_client
from app.agent.protocol import RUNNER_PROTOCOL_VERSION
from test_reader_imports import reading
from test_agent_mvp import client,runner_mock,CANNED_RESULT

@pytest.fixture
def guide_client(reading,monkeypatch):
    c,s,sid,ctx=reading;c.app.include_router(router);c.app.include_router(internal)
    remote=runner_mock(CANNED_RESULT,hang=True)
    async def handler(req):
        if req.url.path=='/health':return httpx.Response(200,json={'status':'ok','protocol_version':RUNNER_PROTOCOL_VERSION})
        return await remote(req)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
    return c,s,sid,ctx

def start(data,key='guide-test'):
    c,s,sid,ctx=data
    r=c.post('/api/reader/papers/1/guide-runs',json={'confirmed':True,'file_version':ctx['file_version'],'request_key':key,'max_pages':2,'max_items':3})
    assert r.status_code==202,r.text
    t=r.json();folder=s.data_dir/'agent';folder.mkdir(exist_ok=True);(folder/'internal-token').write_text('guide-token')
    return t,{'x-research-run-id':t['agent_run_id'],'x-research-tool-token':'guide-token'}

def prepare(data):
    c,s,sid,ctx=data;t,h=start(data)
    context=c.post('/api/internal/reader-guide/context',headers=h).json()
    mat=c.post('/api/internal/reader-guide/material',headers=h,json={'pages':[1]})
    assert mat.status_code==200,mat.text
    mat=mat.json();quote='Research assistants need to read papers quickly.'
    b=next(x for x in mat['blocks'] if quote in x['text'])
    result={'schema_version':'paper-guide/v1','material_manifest_id':context['material_manifest_id'],'summary':{'problem_md':'论文问题','approach_md':'方法概览','contributions_md':'贡献','limitations_md':'只读第一页'},'reading_route':[{'key':'first','title':'研究问题','goal_md':'理解动机','item_keys':['problem-1'],'block_ids':[b['block_id']]}],'items':[{'key':'problem-1','category':'problem','priority':'essential','title':'研究问题','why_important_md':'关联论文任务','explanation_md':'这句说明快速阅读需求。','claim_type':'agent_interpretation','anchors':[{'type':'text','block_id':b['block_id'],'quote':quote}],'follow_up_questions':[],'uncertainties':[]}],'coverage':{'material_ids':mat['material_ids'],'scope':'selected_pages','figures_read':False,'code_read':False,'limitations':['仅第一页']},'unknown_fields':[]}
    return t,h,result

def finish(c,s,t):
    with sqlite3.connect(s.db_path) as db:db.execute("UPDATE agent_runs SET status='succeeded' WHERE id=?",(t['agent_run_id'],))
    return c.get('/api/reader/papers/1/guide').json()

def test_open_refresh_and_skill_picker_do_not_run_models(guide_client):
    c,s,_,_=guide_client
    for _ in range(3):assert c.get('/api/reader/papers/1/guide').json()['task'] is None
    assert c.get('/api/reader/guide-skills').json()['skills'][0]['id']=='paper_guide'
    with sqlite3.connect(s.db_path) as db:
        assert db.execute('SELECT count(*) FROM reader_guide_tasks').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0

def test_requires_explicit_confirmation_and_real_pdf(guide_client):
    c,s,sid,ctx=guide_client
    body={'file_version':ctx['file_version'],'request_key':'no-auto'}
    assert c.post('/api/reader/papers/1/guide-runs',json=body).status_code==422
    assert c.post('/api/reader/papers/1/guide-runs',json={**body,'confirmed':False}).status_code==422
    assert c.post('/api/reader/papers/2/guide-runs',json={**body,'confirmed':True}).status_code==400

def test_semantic_dedup_across_different_client_keys(guide_client):
    c,s,_,_=guide_client;t,_=start(guide_client,'key-one');other,_=start(guide_client,'key-two')
    assert other['id']==t['id'] and other['cached']
    with sqlite3.connect(s.db_path) as db:assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==1

def test_real_quote_projects_verified_geometry_and_survives_reopen(guide_client):
    c,s,sid,ctx=guide_client;t,h,result=prepare(guide_client)
    r=c.post('/api/internal/reader-guide/submit',headers=h,json=result);assert r.status_code==200,r.text
    assert not c.get('/api/reader/papers/1/annotations').json()['annotations']
    data=finish(c,s,t);assert data['guide']['status']=='partial'
    anns=c.get('/api/reader/papers/1/annotations').json()['annotations'];assert len(anns)==1
    a=anns[0];assert a['origin']=='ai' and a['kind']=='highlight' and a['quote']==ctx['quote']
    assert a['rects'] and all(len(v)==4 and all(0<=z<=1 for z in v) for v in a['rects'])
    again=c.get('/api/reader/papers/1/guide').json();assert again['guide']['items'][0]['location_status']=='verified'

def test_duplicate_submission_is_idempotent(guide_client):
    c,s,_,_=guide_client;t,h,result=prepare(guide_client)
    for _ in range(2):assert c.post('/api/internal/reader-guide/submit',headers=h,json=result).status_code==200
    for _ in range(2):finish(c,s,t)
    assert len(c.get('/api/reader/papers/1/annotations').json()['annotations'])==1

def test_no_guessed_blocks_rectangles_or_vision_claims(guide_client):
    c,s,_,_=guide_client;t,h,result=prepare(guide_client)
    bad=json.loads(json.dumps(result));bad['items'][0]['anchors'][0]['block_id']='invented'
    assert c.post('/api/internal/reader-guide/submit',headers=h,json=bad).status_code==422
    bad=json.loads(json.dumps(result));bad['items'][0]['anchors'][0]['rects']=[[.1,.1,.2,.2]]
    assert c.post('/api/internal/reader-guide/submit',headers=h,json=bad).status_code==422
    bad=json.loads(json.dumps(result));bad['coverage']['figures_read']=True
    assert c.post('/api/internal/reader-guide/submit',headers=h,json=bad).status_code==422
    bad=json.loads(json.dumps(result));bad['coverage']['scope']='fulltext'
    assert c.post('/api/internal/reader-guide/submit',headers=h,json=bad).status_code==422
    assert not c.get('/api/reader/papers/1/annotations').json()['annotations']

def test_unmatched_quote_becomes_page_note_not_false_highlight(guide_client):
    c,s,_,_=guide_client;t,h,result=prepare(guide_client);result['items'][0]['anchors'][0]['quote']='This quote does not occur in the PDF.'
    assert c.post('/api/internal/reader-guide/submit',headers=h,json=result).status_code==200
    finish(c,s,t);a=c.get('/api/reader/papers/1/annotations').json()['annotations'][0]
    assert a['kind']=='note' and a['rects']==[] and a['quote']==''

def test_ai_delete_does_not_resurrect_and_adoption_is_personal(guide_client):
    c,s,_,_=guide_client;t,h,result=prepare(guide_client);c.post('/api/internal/reader-guide/submit',headers=h,json=result);g=finish(c,s,t)['guide'];item=g['items'][0]
    a=c.get('/api/reader/papers/1/annotations').json()['annotations'][0]
    assert c.patch('/api/reader/annotations/'+a['id'],json={'content':'silent rewrite'}).status_code==409
    adopted=c.post('/api/reader/guide-items/'+item['id']+'/adopt',json={'request_key':'adopt1'});assert adopted.status_code==200
    again=c.post('/api/reader/guide-items/'+item['id']+'/adopt',json={'request_key':'adopt2'});assert adopted.json()['id']==again.json()['id']
    assert adopted.json()['origin']=='ai_adopted'
    assert c.patch('/api/reader/annotations/'+adopted.json()['id'],json={'content':'我的理解'}).status_code==200
    c.patch('/api/reader/annotations/'+a['id'],json={'deleted':True})
    for _ in range(2):c.get('/api/reader/papers/1/guide')
    remaining=c.get('/api/reader/papers/1/annotations').json()['annotations'];assert len(remaining)==1 and remaining[0]['content']=='我的理解'

def test_unauthorized_and_late_submission_rejected(guide_client):
    c,s,_,_=guide_client;t,h,result=prepare(guide_client)
    assert c.post('/api/internal/reader-guide/context').status_code==403
    with sqlite3.connect(s.db_path) as db:db.execute("UPDATE agent_runs SET status='cancelled' WHERE id=?",(t['agent_run_id'],))
    assert c.post('/api/internal/reader-guide/submit',headers=h,json=result).status_code==403
    assert c.get('/api/reader/papers/1/guide').json()['task']['status']=='cancelled'
    assert c.patch('/api/reader/guide-runs/'+t['id'],json={'hidden':True}).status_code==200
    assert c.get('/api/reader/papers/1/guide').json()['task'] is None

def test_stale_pdf_never_activates_old_coordinates(guide_client):
    import pymupdf
    c,s,_,_=guide_client;t,h,result=prepare(guide_client);c.post('/api/internal/reader-guide/submit',headers=h,json=result)
    path=s.data_dir/'papers/1.pdf'
    with pymupdf.open(path) as doc:doc[0].insert_text((72,200),'new version');doc.saveIncr()
    finish(c,s,t)
    assert c.get('/api/reader/papers/1/guide').json()['guide'] is None
    assert not c.get('/api/reader/papers/1/annotations').json()['annotations']


def test_material_scope_and_manifest_are_bound(guide_client):
    c,s,_,_=guide_client;t,h,result=prepare(guide_client)
    assert c.post('/api/internal/reader-guide/material',headers=h,json={'pages':[0]}).status_code==422
    assert c.post('/api/internal/reader-guide/material',headers=h,json={'pages':[999]}).status_code==422
    result['material_manifest_id']='other-task-manifest'
    assert c.post('/api/internal/reader-guide/submit',headers=h,json=result).status_code==409

def test_duplicate_quote_requires_disambiguation():
    from app.reader.guides.materials import locate,normalized
    from app.reader.guides.schemas import TextAnchor
    block={'id':'block','page':1,'data_json':json.dumps({'norm':'samewordsameword','mapping':[[0,.1,.2,.12,.22]]*16})}
    assert locate(block,TextAnchor(type='text',block_id='block',quote='sameword'))['status']=='ambiguous'
    assert locate(block,TextAnchor(type='text',block_id='block',quote='sameword',prefix='sameword'))['status']=='verified'
    assert normalized('ﬁ  x\n− 1')=='fix-1'
