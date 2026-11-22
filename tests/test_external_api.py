"""Real middleware and isolated workspaces; no paid calls or real credentials."""
import json
import time
from test_auth_accounts import secured,login,user,paper

def token(c,a,scopes=None,ids=None):
    body={'name':'fixture','scopes':scopes or ['papers:read','papers:write','annotations:read','annotations:write','files:read']}
    if ids is not None:body['paper_ids']=ids
    r=c.post('/api/me/access-tokens',headers=a,json=body);assert r.status_code==201,r.text
    return r.json(),{'Authorization':'Bearer '+r.json()['token']}

def test_external_token_boundary_and_revocation(secured):
    c,app=secured;a=login(c);made,h=token(c,a)
    assert c.get('/api/external/v1/capabilities',headers=a).status_code==401
    assert c.get('/api/me',headers=h).status_code==401
    assert c.get('/api/internal/tools/library_search',headers=h).status_code==403
    r=c.get('/api/external/v1/capabilities',headers=h);assert r.status_code==200,r.text
    assert not r.json()['model_operations']
    assert c.get('/api/external/v1/papers',headers={**h,'Origin':'https://evil.example'}).status_code==403
    listed=c.get('/api/me/access-tokens',headers=a);assert made['token'] not in listed.text and 'token_hash' not in listed.text
    assert c.delete('/api/me/access-tokens/'+made['id'],headers=a).status_code==200
    assert c.get('/api/external/v1/papers',headers=h).status_code==401

def test_external_expiry_password_and_rate(secured):
    c,app=secured;a=login(c);made,h=token(c,a)
    db=app.state.auth_store.db
    db.execute('UPDATE external_tokens SET rate_window=?,rate_count=60 WHERE id=?',(int(time.time())//60,made['id']));db.commit()
    assert c.get('/api/external/v1/papers',headers=h).status_code==429
    db.execute('UPDATE external_tokens SET expires_at=0 WHERE id=?',(made['id'],));db.commit()
    assert c.get('/api/external/v1/papers',headers=h).status_code==401
    _,h=token(c,a)
    db.execute('UPDATE accounts SET session_version=session_version+1');db.commit()
    assert c.get('/api/external/v1/papers',headers=h).status_code==401

def test_cross_account_scope_and_restricted_pagination(secured):
    c,app=secured;a=login(c);paper(app.state)
    made,h=token(c,a,['papers:read'],[1])
    other,account,a=user(c,app)
    assert c.delete('/api/me/access-tokens/'+made['id'],headers=other).status_code==404
    assert c.get('/api/me/access-tokens',headers=other).json()['tokens']==[]
    _,oh=token(c,other,['papers:read'])
    assert c.get('/api/external/v1/papers/1',headers=oh).status_code==404
    for title in ('other','more'):app.state.db.execute('INSERT INTO papers(title) VALUES (?)',(title,))
    app.state.db.commit()
    r=c.get('/api/external/v1/papers?limit=1',headers=h);assert r.status_code==200,r.text
    assert r.json()['total']==1 and not r.json()['has_more']
    assert c.get('/api/external/v1/papers/2',headers=h).status_code==404
    assert c.get('/api/external/v1/collections',headers=h).status_code==404
    assert c.post('/api/external/v1/papers',headers={**h,'Idempotency-Key':'x'},json={'title':'blocked'}).status_code==403
    _,rh=token(c,a,['papers:write'],[1])
    assert c.post('/api/external/v1/papers',headers={**rh,'Idempotency-Key':'x'},json={'title':'blocked'}).status_code==404

def test_metadata_idempotency_version_and_atomic_audit(secured):
    c,app=secured;a=login(c);_,h=token(c,a)
    url='/api/external/v1/papers';headers={**h,'Idempotency-Key':'create'}
    body={'title':'New','authors':['Author']}
    r=c.post(url,headers=headers,json=body);assert r.status_code==201,r.text
    p=r.json();assert 'pdf_path' not in p
    assert c.post(url,headers=headers,json=body).json()==p
    assert c.post(url,headers=headers,json={'title':'Different'}).status_code==409
    assert app.state.db.execute('SELECT count(*) FROM papers').fetchone()[0]==1
    assert app.state.db.execute('SELECT count(*) FROM external_audit').fetchone()[0]==1
    assert c.post(url,headers=h,json=body).status_code==422
    patch={'title':'Edited','metadata_version':p['metadata_version']}
    r=c.patch(url+'/'+str(p['id']),headers={**h,'Idempotency-Key':'edit'},json=patch);assert r.status_code==200,r.text
    assert r.json()['metadata_version']==p['metadata_version']+1
    assert c.patch(url+'/'+str(p['id']),headers={**h,'Idempotency-Key':'stale'},json=patch).status_code==409
    assert c.patch(url+'/'+str(p['id']),headers={**h,'Idempotency-Key':'bad'},json={**patch,'pdf_path':'/etc/passwd'}).status_code==422
    assert app.state.db.execute('SELECT count(*) FROM external_operations').fetchone()[0]==2

def test_annotation_evidence_etag_and_soft_delete(secured):
    c,app=secured;a=login(c);paper(app.state);_,h=token(c,a)
    base='/api/external/v1/papers/1'
    info=c.get(base+'/document',headers=h);assert info.status_code==200,info.text
    assert info.json()['pdf_url']==base+'/file'
    assert c.get(base+'/file',headers=h).content.startswith(b'%PDF')
    assert c.get(base+'/pages/1',headers=h).json()['text_source']=='original_pdf_page'
    body={'paper_id':1,'page':1,'file_version':info.json()['file_version'],'kind':'note','content':'Evidence note'}
    post=c.post(base+'/annotations',headers={**h,'Idempotency-Key':'note'},json=body);assert post.status_code==201,post.text
    note=post.json();assert len(note['etag'])==64
    assert c.post(base+'/annotations',headers={**h,'Idempotency-Key':'bad-hash'},json={**body,'file_version':'0'*64}).status_code==409
    assert c.post(base+'/annotations',headers={**h,'Idempotency-Key':'bad-id'},json={**body,'paper_id':2}).status_code==422
    url=base+'/annotations/'+note['id']
    change={'expected_etag':note['etag'],'content':'Edited note'}
    edit=c.patch(url,headers={**h,'Idempotency-Key':'edit-note'},json=change);assert edit.status_code==200,edit.text
    assert c.patch(url,headers={**h,'Idempotency-Key':'stale-note'},json=change).status_code==409
    assert c.patch(url,headers={**h,'Idempotency-Key':'delete-note'},json={'expected_etag':edit.json()['etag'],'deleted':True}).json()['deleted']
    row=app.state.db.execute('SELECT * FROM reader_annotations').fetchone();assert row['content']=='Edited note'

def test_request_size_and_no_secret_errors(secured):
    c,_=secured;a=login(c);made,h=token(c,a)
    r=c.post('/api/external/v1/papers',headers={**h,'Idempotency-Key':'big'},content=b'x'*65537);assert r.status_code==413
    assert made['token'] not in r.text
    def chunks():yield b'x'*40000;yield b'x'*40000
    assert c.post('/api/external/v1/papers',headers=h,content=chunks()).status_code==413

def test_deleted_annotation_can_be_found_and_restored(secured):
    c,app=secured;a=login(c);paper(app.state);_,h=token(c,a)
    base='/api/external/v1/papers/1';version=c.get(base+'/document',headers=h).json()['file_version']
    n=c.post(base+'/annotations',headers={**h,'Idempotency-Key':'make'},json={'paper_id':1,'page':1,'file_version':version,'kind':'note','content':'Restore me'}).json()
    url=base+'/annotations/'+n['id']
    deleted=c.patch(url,headers={**h,'Idempotency-Key':'remove'},json={'expected_etag':n['etag'],'deleted':True});assert deleted.status_code==200
    assert c.get(base+'/annotations',headers=h).json()['annotations']==[]
    current=c.get(url,headers=h);assert current.status_code==200 and current.json()['deleted']
    assert c.get(base+'/annotations?include_deleted=true',headers=h).json()['annotations'][0]['etag']==current.json()['etag']
    stale=c.patch(url,headers={**h,'Idempotency-Key':'stale'},json={'expected_etag':n['etag'],'deleted':False})
    assert stale.status_code==409 and stale.json()['code']=='annotation_conflict'
    restored=c.patch(url,headers={**h,'Idempotency-Key':'restore'},json={'expected_etag':current.json()['etag'],'deleted':False});assert restored.status_code==200 and not restored.json()['deleted']
    _,limited=token(c,a,['annotations:read'],[1])
    assert c.get('/api/external/v1/papers/2/annotations/'+n['id'],headers=limited).status_code==404

def test_explicit_conflicts_are_machine_readable(secured):
    c,app=secured;a=login(c);paper(app.state);_,h=token(c,a)
    url='/api/external/v1/papers/1'
    b={'title':'Changed','metadata_version':1}
    assert c.patch(url,headers={**h,'Idempotency-Key':'op'},json=b).status_code==200
    r=c.patch(url,headers={**h,'Idempotency-Key':'op'},json={**b,'title':'Other'});assert r.json()['code']=='idempotency_conflict'
    r=c.patch(url,headers={**h,'Idempotency-Key':'new-op'},json=b);assert r.json()['code']=='metadata_conflict'
