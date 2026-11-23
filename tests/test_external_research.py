"""New research contracts respect account scopes and paper whitelists."""
from test_auth_accounts import secured,login,paper,user
from test_external_api import token


def test_artifact_whitelist_idempotency_and_candidate_only(secured):
    c,app=secured;a=login(c);paper(app.state)
    app.state.db.execute("INSERT INTO papers(id,title) VALUES (2,'Other paper')");app.state.db.commit()
    _,h=token(c,a,['artifacts:read','artifacts:write','knowledge:read','knowledge:write','runs:read'],[1])
    path='/api/external/v1/artifacts';body={'title':'Local reading','markdown':'Local result','paper_ids':[1],'status':'complete'}
    headers={**h,'Idempotency-Key':'artifact-one'}
    r=c.post(path,headers=headers,json=body);assert r.status_code==201,r.text
    ident=r.json()['id'];assert c.post(path,headers=headers,json=body).json()['id']==ident
    assert c.post(path,headers={**h,'Idempotency-Key':'outside'},json={**body,'paper_ids':[2]}).status_code==404
    assert len(c.get(path,headers=h).json()['artifacts'])==1
    k=c.post('/api/external/v1/knowledge/candidates',headers={**h,'Idempotency-Key':'knowledge-one'},json={'title':'Finding','markdown':'Interpretation','sources':[{'artifact_id':ident,'revision':1}],'claim_type':'inference'})
    assert k.status_code==201,k.text
    assert c.get('/api/external/v1/knowledge/recall',headers=h).json()['knowledge']==[]
    assert c.post('/api/external/v1/knowledge/'+k.json()['id']+'/transition',headers=h,json={'action':'publish'}).status_code in (404,405)
    _,limited=token(c,a,['papers:read'],[1])
    assert c.get(path+'/'+ident,headers=limited).status_code==403
    other,account,_=user(c,app);_,foreign=token(c,other,['artifacts:read'])
    assert c.get(path+'/'+ident,headers=foreign).status_code==404


def test_file_upload_is_paper_scoped_and_does_not_create_model_run(secured):
    c,app=secured;a=login(c);paper(app.state)
    _,h=token(c,a,['artifacts:read','artifacts:write'],[1])
    r=c.post('/api/external/v1/files',headers=h,data={'paper_id':1},files={'file':('local.md',b'# Result')});assert r.status_code==201,r.text
    assert c.get('/api/external/v1/files/'+r.json()['hash'],headers=h).content==b'# Result'
    assert c.post('/api/external/v1/files',headers=h,data={'paper_id':2},files={'file':('local.md',b'# Result')}).status_code==404
    assert app.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0
