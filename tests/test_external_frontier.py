import json
from test_auth_accounts import secured,login,user
from test_external_api import token

def payload():
    return {'topic_revision':1,'producer':'Local test agent','window_start':'2026-11-01T00:00:00Z','window_end':'2026-11-22T00:00:00Z','markdown':'Discovery [证据:p1]','searches':[{'source':'arxiv','query':'robot','status':'complete','records':[{'ref':'p1','metadata':{'kind':'paper','title':'Actual candidate','arxiv_id':'1706.03762','url':'https://arxiv.org/abs/1706.03762','evidence_level':'abstract','abstract':'Evidence'}}]}],'citations':['p1'],'reasons':{'p1':'Relevant'}}

def setup(c,a):
    _,h=token(c,a,['frontier:read','frontier:write'])
    r=c.post('/api/external/v1/frontier/topics',headers={**h,'Idempotency-Key':'topic'},json={'title':'Local research','config':{'keywords':['robot'],'sources':['arxiv'],'max_results':5}})
    assert r.status_code==201,r.text
    return r.json()['id'],h

def test_upload_timeline_dedup_retry_and_no_server_run(secured):
    c,app=secured;a=login(c);tid,h=setup(c,a);base=f'/api/external/v1/frontier/topics/{tid}/reports'
    before=app.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]
    r=c.post(base,headers={**h,'Idempotency-Key':'report1'},json=payload());assert r.status_code==201,r.text
    result=r.json();ident=result['run']['id'];assert result['verification']=='caller_supplied' and not result['model_called']
    assert result['run']['origin']=='external' and result['run']['status']=='succeeded'
    assert c.post(base,headers={**h,'Idempotency-Key':'report1'},json=payload()).json()==result
    current=c.get('/api/external/v1/frontier/reports/'+ident,headers=h);assert current.status_code==200
    assert '[证据:'+result['evidence_ids']['p1']+']' in current.json()['report_md']
    second=c.post(base,headers={**h,'Idempotency-Key':'report2'},json=payload());assert second.status_code==201,second.text
    assert second.json()['run']['counts']['known']==1
    assert app.state.db.execute('SELECT count(*) FROM frontier_entities').fetchone()[0]==1
    assert app.state.db.execute('SELECT count(*) FROM papers').fetchone()[0]==0
    assert app.state.db.execute('SELECT count(*) FROM frontier_cursors').fetchone()[0]==0
    assert app.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==before
    assert app.state.db.execute('SELECT enabled FROM research_schedules').fetchone()[0]==0
    timeline=c.get('/api/frontier/reports',headers=a);assert timeline.status_code==200,timeline.text
    assert len(timeline.json()['reports'])==2 and timeline.json()['reports'][0]['origin']=='external'
    items=c.get('/api/frontier/candidates',headers=a).json()['items'];assert items[0]['decision']=='pending'
    assert c.get('/api/external/v1/frontier/reports?limit=1',headers=h).json()['next_cursor']

def test_upload_scope_isolation_and_atomic_validation(secured):
    c,app=secured;a=login(c);tid,h=setup(c,a);base=f'/api/external/v1/frontier/topics/{tid}/reports'
    _,readonly=token(c,a,['frontier:read'])
    assert c.post(base,headers={**readonly,'Idempotency-Key':'denied'},json=payload()).status_code==403
    _,paper_only=token(c,a,['papers:read'])
    assert c.get('/api/external/v1/frontier/topics',headers=paper_only).status_code==403
    other,_,a=user(c,app);_,foreign=token(c,other,['frontier:write'])
    assert c.post(base,headers={**foreign,'Idempotency-Key':'foreign'},json=payload()).status_code==404
    for body in ({**payload(),'topic_revision':2},{**payload(),'citations':['invented']},{**payload(),'searches':[{**payload()['searches'][0],'source':'crossref'}]}):
        r=c.post(base,headers={**h,'Idempotency-Key':'bad'},json=body);assert r.status_code in (409,422),r.text
    assert app.state.db.execute('SELECT count(*) FROM frontier_reports').fetchone()[0]==0
    assert app.state.db.execute('SELECT count(*) FROM frontier_runs').fetchone()[0]==0
    assert c.post('/api/me/access-tokens',headers=a,json={'name':'bad scope','scopes':['frontier:read'],'paper_ids':[1]}).status_code==422


def test_upload_rolls_back_evidence_if_report_save_fails(secured,monkeypatch):
    from app.frontier import service
    from app.core.errors import ServiceError
    c,app=secured;a=login(c);tid,h=setup(c,a)
    before=app.state.db.execute('SELECT count(*) FROM external_operations').fetchone()[0]
    def fail(*args):raise ServiceError(400,'fixture report failure')
    monkeypatch.setattr(service,'save_report',fail)
    r=c.post(f'/api/external/v1/frontier/topics/{tid}/reports',headers={**h,'Idempotency-Key':'atomic'},json=payload());assert r.status_code==400
    for table in ('frontier_runs','frontier_reports','frontier_entities','frontier_evidence','frontier_items'):
        assert app.state.db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
    assert app.state.db.execute('SELECT count(*) FROM external_operations').fetchone()[0]==before
