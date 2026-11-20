"""Manual device exchange, tenant isolation, immutable PDFs and retry contracts."""
import hashlib
import json
from types import SimpleNamespace
import pytest
from test_auth_accounts import secured,login,user,run_async,ADMIN_PASSWORD,USER_PASSWORD
from test_documents import pdf


def paired(c,headers,name='Desktop'):
    p=c.post('/api/zotero/pair/start',json={'name':name,'instance_id':'desktop-instance-'+name});assert p.status_code==200,p.text
    p=p.json();claim={'pair_id':p['pair_id'],'device_code':p['device_code']}
    assert c.post('/api/zotero/pair/claim',json=claim).json()['status']=='pending'
    assert c.post('/api/zotero/pair/approve',headers=headers,json={'user_code':p['user_code']}).status_code==200
    r=c.post('/api/zotero/pair/claim',json=claim);assert r.status_code==200,r.text
    assert c.post('/api/zotero/pair/claim',json=claim).status_code==404
    device=r.json();return {'Authorization':'Bearer '+device['token']},device


def body(**kw):return {'library_key':'1','item_key':'ABC12345','title':'Robotics paper','doi':'10.1234/example','authors':['A Researcher'],'tags':['robot'],'collection_paths':[['Robotics','Reading'],['Vision','Reading']],**kw}


def imported(c,h,**kw):
    r=c.post('/api/zotero/device/items',headers=h,json=body(**kw));assert r.status_code==200,r.text
    return r.json()['paper_id']


def test_device_credentials_replay_scope_revocation_and_password(secured):
    c,a=secured;admin=login(c);h,d=paired(c,admin)
    assert c.get('/api/me',headers=h).status_code==401
    assert c.get('/api/admin/accounts',headers=h).status_code==401
    assert c.post('/api/zotero/device/items',headers=admin,json=body()).status_code==401
    assert d['token'] not in str(a.state.auth_store.db.execute('SELECT * FROM zotero_devices').fetchall())
    imported(c,h)
    assert c.delete('/api/zotero/devices/'+d['device_id'],headers=admin).status_code==200
    assert c.post('/api/zotero/device/items',headers=h,json=body()).status_code==401
    h,_=paired(c,admin)
    c.post('/api/auth/password',headers=admin,json={'current_password':ADMIN_PASSWORD,'new_password':USER_PASSWORD})
    assert c.post('/api/zotero/device/items',headers=h,json=body()).status_code==401


def test_hierarchy_dedup_and_manual_edits_are_preserved(secured):
    c,a=secured;admin=login(c);h,d=paired(c,admin);pid=imported(c,h)
    assert imported(c,h)==pid
    db=a.state.db
    assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==1
    assert db.execute("SELECT count(*) FROM paper_collections WHERE name='Reading'").fetchone()[0]==2
    root=db.execute('SELECT id FROM paper_collections WHERE parent_id IS NULL').fetchone()[0]
    assert c.get(f'/api/library/papers?collection_id={root}',headers=admin).json()['total']==1
    assert c.get('/api/library/papers',headers=admin).json()['papers'][0]['tags']==['robot']
    db.execute('UPDATE papers SET title=?,metadata_version=metadata_version+1 WHERE id=?',('My edit',pid));db.commit()
    r=c.post('/api/zotero/device/items',headers=h,json=body(title='Source edit'));assert r.status_code==409
    assert db.execute('SELECT title FROM papers').fetchone()[0]=='My edit'
    assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0


def test_isolated_devices_cannot_cross_account_papers_or_jobs(secured):
    c,a=secured;member,account,admin=user(c,a);ha,da=paired(c,admin);hb,db=paired(c,member)
    pid=imported(c,ha)
    assert c.get('/api/zotero/devices',headers=member).json()['devices'][0]['id']==db['device_id']
    assert c.delete('/api/zotero/devices/'+da['device_id'],headers=member).status_code==404
    assert c.post('/api/zotero/exports',headers=member,json={'device_id':da['device_id'],'paper_ids':[pid],'request_key':'isolation'}).status_code==404
    fields={'library_key':'1','item_key':'ABC12345','attachment_key':'PDF12345','label':'v1'}
    assert c.post(f'/api/zotero/device/papers/{pid}/attachments',headers=hb,data=fields,files={'file':('x.pdf',pdf(),'application/pdf')}).status_code==404
    assert c.post('/api/zotero/device/exports/claim',headers=hb,json={}).json()['job'] is None
    assert imported(c,hb,title='Other account')==pid
    state=run_async(c,a.state.workspaces.get(account['workspace_key']))
    assert state.db.execute('SELECT title FROM papers').fetchone()[0]=='Other account'
    assert a.state.db.execute('SELECT title FROM papers').fetchone()[0]=='Robotics paper'


def test_pdf_hash_retry_export_scope_and_idempotent_ack(secured):
    c,a=secured;admin=login(c);h,d=paired(c,admin);other,od=paired(c,admin,'Other');pid=imported(c,h)
    a.state.embedder=SimpleNamespace(dimension=4,embed=lambda texts:[[1.,0.,0.,0.] for _ in texts])
    raw=pdf('Source text');fields={'library_key':'1','item_key':'ABC12345','attachment_key':'PDF12345','label':'v1','role':'main'}
    url=f'/api/zotero/device/papers/{pid}/attachments'
    r=c.post(url,headers=h,data=fields,files={'file':('x.pdf',raw,'application/pdf')});assert r.status_code==200,r.text
    vid=r.json()['version_id'];assert r.json()['has_default_pdf']
    r=c.post(url,headers=h,data=fields,files={'file':('x.pdf',raw,'application/pdf')});assert r.json()['version_id']==vid
    check={k:fields[k] for k in ('library_key','item_key','attachment_key')};check['file_hash']=hashlib.sha256(raw).hexdigest()
    assert c.post(url+'/check',headers=h,json=check).json()['present']
    payload={'device_id':d['device_id'],'paper_ids':[pid],'request_key':'send-paper-1'}
    r=c.post('/api/zotero/exports',headers=admin,json=payload);assert r.status_code==200,r.text
    ident=r.json()['jobs'][0]['id']
    assert c.post('/api/zotero/exports',headers=admin,json=payload).json()['jobs'][0]['id']==ident
    job=c.post('/api/zotero/device/exports/claim',headers=h,json={}).json()['job']
    path=f'/api/zotero/device/exports/{ident}/files/{vid}'
    assert c.get(path,headers=h).status_code==409
    assert c.get(path,headers={**other,'X-Sync-Lease':job['lease_token']}).status_code==409
    assert c.get(path,headers={**h,'X-Sync-Lease':job['lease_token']}).content==raw
    ack={'lease_token':job['lease_token'],'success':True,'library_key':'1','item_key':'ABC12345','attachments':{vid:'PDF12345'}}
    assert c.post(f'/api/zotero/device/exports/{ident}/ack',headers=h,json=ack).status_code==200
    assert c.post(f'/api/zotero/device/exports/{ident}/ack',headers=h,json=ack).status_code==200
    assert c.get(path,headers={**h,'X-Sync-Lease':job['lease_token']}).status_code==409
    assert a.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0


def test_repair_preserves_source_identity_and_expires_previous_token(secured):
    c,a=secured;admin=login(c);h,d=paired(c,admin);pid=imported(c,h,doi='')
    fresh,again=paired(c,admin)
    assert again['device_id']==d['device_id']
    assert c.post('/api/zotero/device/items',headers=h,json=body(doi='')).status_code==401
    assert imported(c,fresh,doi='')==pid
    a.state.auth_store.db.execute('UPDATE zotero_devices SET expires_at=0');a.state.auth_store.db.commit()
    assert c.post('/api/zotero/device/items',headers=fresh,json=body()).status_code==401


def test_identifier_normalization_and_invalid_ack_leave_no_partial_state(secured):
    c,a=secured;admin=login(c);h,d=paired(c,admin)
    pid=imported(c,h,doi='https://dx.doi.org/10.1234/EXAMPLE',arxiv_id='arXiv:2401.12345v2')
    r=a.state.db.execute('SELECT doi,arxiv_id FROM papers').fetchone()
    assert tuple(r)==('10.1234/example','2401.12345')
    before=a.state.db.execute('SELECT count(*) FROM zotero_links').fetchone()[0]
    assert c.post('/api/zotero/device/items',headers=h,json=body(item_key='OTHER123',doi='invalid')).status_code==422
    assert a.state.db.execute('SELECT count(*) FROM zotero_links').fetchone()[0]==before
    payload={'device_id':d['device_id'],'paper_ids':[pid],'request_key':'send-invalid-ack'}
    c.post('/api/zotero/exports',headers=admin,json=payload)
    job=c.post('/api/zotero/device/exports/claim',headers=h,json={}).json()['job']
    ack={'lease_token':job['lease_token'],'success':True,'library_key':'1','item_key':'ABC12345','attachments':{'not-in-job':'OTHER123'}}
    assert c.post('/api/zotero/device/exports/'+job['id']+'/ack',headers=h,json=ack).status_code==422
    assert a.state.db.execute('SELECT status FROM zotero_exports').fetchone()[0]=='leased'
