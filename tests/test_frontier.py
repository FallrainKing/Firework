"""No paid calls: real migrations, Agent boundary doubles, and approval races."""
import asyncio,json,uuid,sqlite3
from test_agent_mvp import client
from types import SimpleNamespace
import pytest
from app.core.config import Settings
from app.core.db import get_conn
from app.core.errors import ServiceError
from app.frontier import service as f,identity
from app.frontier.schemas import TopicCreate,TopicConfig,Decision,Report

@pytest.fixture
def db(tmp_path):
    d=get_conn(Settings(data_dir=tmp_path,qdrant_url='unused'))
    yield d
    d.close()

@pytest.fixture
def topic(db):return f.save_topic(db,TopicCreate(title='机器人',config=TopicConfig(keywords=['robot'],sources=['crossref','github'])))

def draft(db,topic):
    ident=uuid.uuid4().hex
    db.execute("INSERT INTO frontier_runs(id,topic_id,revision,config_json,request_key,window_start,window_end,status) VALUES (?,?,?,?,?,'2026-11-01','2026-11-19','failed')",(ident,topic['id'],1,json.dumps(topic['config']),ident));db.commit()
    return f.require(db,'frontier_runs',ident)

def paper(**extra):return dict(kind='paper',title='Robot Learning',doi='10.1234/test',url='https://doi.org/10.1234/test',abstract='Real abstract',authors=['A'],evidence_level='abstract',**extra)
def stage(db,r,m):return f.ingest(db,r,'crossref','robot',{'records':[m],'total':1,'truncated':False})['items'][0]
def decide(db,t,e,action='approve',**extra):
    item=db.execute('SELECT revision FROM frontier_items WHERE topic_id=? AND entity_id=?',(t['id'],e)).fetchone()
    return asyncio.run(f.decide(db,SimpleNamespace(),t['id'],e,Decision(action=action,revision=item[0],request_key=uuid.uuid4().hex,**extra)))

def test_topic_paused_and_versions(db,topic):
    assert topic['schedule']['enabled']==0
    assert db.execute('SELECT count(*) FROM frontier_topic_versions').fetchone()[0]==1
    assert topic['config']['sources']==['crossref','github']

def test_normalizes_ids_and_does_not_use_stars():
    assert identity.identifiers({'doi':'https://doi.org/10.1234/TEST'})==['doi:10.1234/test']
    assert identity.identifiers({'arxiv_id':'2401.12345v2'})==['arxiv:2401.12345']
    a={'kind':'project','title':'a','url':'https://github.com/Org/Repo.git','stars':1}
    assert identity.identifiers(a)==['repo:org/repo']
    assert identity.fingerprint(a)==identity.fingerprint({**a,'stars':500,'activity_at':'today'})

def test_existing_library_found_on_first_search(db,topic):
    pid=db.execute("INSERT INTO papers(title,doi,source) VALUES ('Existing','10.1234/test','upload')").lastrowid;db.commit()
    x=stage(db,draft(db,topic),paper());assert x['change_type']=='in_library' and x['paper_id']==pid
    assert f.items(db,topic['id'])[0]['in_library']
    assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==1

def test_dedup_across_topics_and_repeated_search(db,topic):
    a=stage(db,draft(db,topic),paper())
    other=f.save_topic(db,TopicCreate(title='另一个主题',config=TopicConfig(keywords=['robot'],sources=['crossref'])))
    b=stage(db,draft(db,other),paper())
    assert a['entity_id']==b['entity_id'] and b['change_type']=='known'
    assert db.execute('SELECT count(*) FROM frontier_items').fetchone()[0]==2
    assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==0

def test_metadata_approval_is_idempotent(db,topic):
    x=stage(db,draft(db,topic),paper());eid=x['entity_id']
    body=Decision(action='approve',revision=1,request_key='approval1')
    one=asyncio.run(f.decide(db,SimpleNamespace(),topic['id'],eid,body));two=asyncio.run(f.decide(db,SimpleNamespace(),topic['id'],eid,body))
    assert one==two and one['paper_id']
    assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==1
    assert db.execute('SELECT pdf_path FROM papers').fetchone()[0] is None

def test_manual_import_between_discovery_and_approval(db,topic):
    x=stage(db,draft(db,topic),paper())
    pid=db.execute("INSERT INTO papers(title,doi,source) VALUES ('Manual','10.1234/test','import')").lastrowid;db.commit()
    out=decide(db,topic,x['entity_id'])
    assert out['paper_id']==pid and db.execute('SELECT count(*) FROM papers').fetchone()[0]==1

def test_ignore_and_meaningful_version_update(db,topic):
    x=stage(db,draft(db,topic),paper());decide(db,topic,x['entity_id'],'ignore')
    assert stage(db,draft(db,topic),paper())['change_type']=='known'
    changed=paper();changed['abstract']='New material'
    assert stage(db,draft(db,topic),changed)['change_type']=='updated'
    assert f.items(db,topic['id'])[0]['decision']=='ignored'

def test_same_title_different_identity_requires_confirmation(db,topic):
    db.execute("INSERT INTO papers(title,doi,source) VALUES ('Robot Learning','10.1234/other','import')");db.commit()
    x=stage(db,draft(db,topic),paper())
    with pytest.raises(ServiceError):decide(db,topic,x['entity_id'])
    out=decide(db,topic,x['entity_id'],confirm_distinct=True);assert out['paper_id']

def test_project_is_not_fake_paper(db,topic):
    r=draft(db,topic);m={'kind':'project','title':'Org/Repo','url':'https://github.com/Org/Repo','repo_id':123,'description':'real project','owner':'Org'}
    x=f.ingest(db,r,'github','robot',{'records':[m],'total':1})['items'][0]
    out=decide(db,topic,x['entity_id'])
    assert out['project_id'] and not out['paper_id']
    assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==0

def test_report_cannot_cite_invented_evidence(db,topic):
    r=draft(db,topic);x=stage(db,r,paper())
    with pytest.raises(ServiceError):f.save_report(db,r,Report(markdown='fake',citations=['invented']))
    f.save_report(db,r,Report(markdown='real',citations=[x['evidence_id']]))
    assert f.require(db,'frontier_runs',r['id'])['report_md']=='real'

def test_source_failure_and_truncation_are_explicit(db,topic):
    r=draft(db,topic)
    f.ingest(db,r,'github','robot',error='限流')
    f.ingest(db,r,'crossref','robot',{'records':[paper()],'total':100,'truncated':True})
    coverage=json.loads(f.require(db,'frontier_runs',r['id'])['coverage_json'])
    assert coverage[0]['status']=='failed' and coverage[1]['truncated']
    assert not db.execute('SELECT * FROM frontier_cursors').fetchone()

def test_optimistic_approval_conflict(db,topic):
    x=stage(db,draft(db,topic),paper());decide(db,topic,x['entity_id'],'ignore')
    with pytest.raises(ServiceError):asyncio.run(f.decide(db,SimpleNamespace(),topic['id'],x['entity_id'],Decision(action='approve',revision=1,request_key='stale')))


def test_http_end_to_end_with_tool_evidence(client,monkeypatch):
    from app.frontier.router import router,internal
    from app.agent import runner_client
    from test_agent_mvp import runner_mock,CANNED_RESULT
    import httpx
    c,settings=client;c.app.include_router(router);c.app.include_router(internal)
    async def handler(req):
        if req.url.path=='/health':return httpx.Response(200,json={'status':'ok','protocol_version':__import__('app.agent.protocol',fromlist=['RUNNER_PROTOCOL_VERSION']).RUNNER_PROTOCOL_VERSION})
        return await runner_mock_handler(req)
    runner_mock_handler=runner_mock(CANNED_RESULT,hang=True)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test'))
    async def search(*args,**kwargs):return {'records':[paper()],'total':1,'truncated':False}
    monkeypatch.setattr('app.frontier.sources.search',search)
    t=c.post('/api/frontier/topics',json={'title':'端到端验证','config':{'keywords':['robot'],'sources':['crossref']}})
    assert t.status_code==201
    tid=t.json()['id'];run=c.post(f'/api/frontier/topics/{tid}/runs',json={'request_key':'http-run'})
    assert run.status_code==202;run=run.json();aid=run['agent_run_id']
    folder=settings.data_dir/'agent';folder.mkdir(exist_ok=True);(folder/'internal-token').write_text('test-secret')
    headers={'x-research-run-id':aid,'x-research-tool-token':'test-secret'}
    assert c.post('/api/internal/frontier/context',headers={'x-research-run-id':aid}).status_code==403
    assert c.post('/api/internal/frontier/context',headers=headers).json()['topic_id']==tid
    result=c.post('/api/internal/frontier/search',headers=headers,json={'source':'crossref','query':'robot'})
    assert result.status_code==200
    evidence=result.json()['items'][0]
    saved=c.post('/api/internal/frontier/report',headers=headers,json={'markdown':'可溯源报告','citations':[evidence['evidence_id']]})
    assert saved.status_code==200
    assert c.get('/api/frontier/reports').json()['reports']==[]
    with sqlite3.connect(settings.db_path) as db:db.execute("UPDATE agent_runs SET status='succeeded' WHERE id=?",(aid,))
    timeline=c.get('/api/frontier/reports').json()['reports'];assert len(timeline)==1 and timeline[0]['report_md']=='可溯源报告'
    assert c.patch('/api/frontier/reports/'+run['id']+'/read-state').status_code==200
    approve=c.post(f"/api/frontier/topics/{tid}/items/{evidence['entity_id']}/decision",json={'action':'approve','revision':1,'request_key':'http-approve'})
    assert approve.status_code==200 and approve.json()['paper_id']
    assert c.get('/api/frontier/reports').json()['reports'][0]['items'][0]['in_library']
    assert c.post('/api/internal/frontier/report',headers=headers,json={'markdown':'late','citations':[]}).status_code==403


def test_frontier_continues_in_independent_discussion(client,monkeypatch):
    from app.frontier.router import router
    c,settings=client;c.app.include_router(router)
    t=c.post('/api/frontier/topics',json={'title':'主题','config':{'keywords':['robot']}}).json()
    db=c.app.state.db;r=draft(db,t)
    db.execute("UPDATE frontier_runs SET status='succeeded',report_md='本期发现',finished_at=CURRENT_TIMESTAMP WHERE id=?",(r['id'],));db.commit()
    one=c.post('/api/frontier/runs/'+r['id']+'/discussion');two=c.post('/api/frontier/runs/'+r['id']+'/discussion')
    assert one.status_code==200 and one.json()==two.json()
    session=c.get('/api/sessions/'+str(one.json()['session_id'])).json()['session']
    assert session['skill']=='chat' and r['id'] in session['draft_prompt']


def test_backfill_is_repeatable_and_keeps_existing_metadata(db):
    db.execute("INSERT INTO papers(title,doi,source,status) VALUES ('Old','10.1234/old','upload','read')");db.commit()
    f.sync_existing_library(db);f.sync_existing_library(db)
    assert db.execute('SELECT count(*) FROM frontier_entities').fetchone()[0]==1
    assert db.execute('SELECT title,status FROM papers').fetchone()[:]==('Old','read')
    assert db.execute('SELECT frontier_entity_id FROM papers').fetchone()[0]


def test_release_fetch_failure_does_not_create_false_update(db,topic):
    r=draft(db,topic);m={'kind':'project','title':'Org/Repo','url':'https://github.com/Org/Repo','description':'project','release':{'id':1,'tag':'v1'},'release_checked':True}
    x=f.ingest(db,r,'github','robot',{'records':[m]})['items'][0]
    later={k:v for k,v in m.items() if k!='release'};later['release_checked']=False
    y=f.ingest(db,draft(db,topic),'github','robot',{'records':[later]})['items'][0]
    assert x['entity_id']==y['entity_id'] and y['change_type']=='known'


def test_candidate_cursor_pages_are_stable(db,topic):
    for index in range(4):
        m=paper();m['doi']=f'10.1234/item{index}';m['title']=f'Paper {index}'
        stage(db,draft(db,topic),m)
    first=f.items(db,topic['id'],limit=2)
    cursor=str(first[-1]['id'])+':'+str(topic['id'])
    second=f.items(db,topic['id'],cursor,limit=2)
    assert len(first)==len(second)==2
    assert not {x['id'] for x in first}&{x['id'] for x in second}
