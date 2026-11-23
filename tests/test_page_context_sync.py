"""R1/R5 contracts with real per-user authorization and actual PDFs, no model calls."""
import json,time
from test_auth_accounts import secured,login,paper,user
from test_external_api import token

def setup(c,app):
    a=login(c);paper(app.state)
    r=c.get('/api/reader/papers/1',headers=a);assert r.status_code==200,r.text
    d=r.json();text=c.get('/api/reader/papers/1/pages/1',headers=a).json()['text'].strip()
    return a,d,text

def test_context_expiry_whitelist_revision_and_logout(secured):
    c,app=secured;a,d,text=setup(c,app)
    r=c.post('/api/workbench/contexts',headers=a);assert r.status_code==201,r.text
    ident=r.json()['id'];path='/api/workbench/contexts/'+ident
    body={'workspace_id':'a'*32,'revision':1,'view':'reader','resource':{'paper_id':1,'file_hash':d['file_version']},'page':1,'shared':False,'has_focus':True}
    assert c.put(path,headers=a,json=body).status_code==200
    _,h=token(c,a,['context:read','papers:read'],[1])
    assert c.get('/api/external/v1/contexts',headers=h).json()['contexts']==[]
    body.update(shared=True,revision=2)
    assert c.put(path,headers=a,json=body).status_code==200
    items=c.get('/api/external/v1/contexts',headers=h);assert items.status_code==200,items.text
    assert len(items.json()['contexts'])==1
    assert c.get('/api/external/v1/contexts/'+ident+'?expected_revision=0',headers=h).status_code==409
    assert c.get('/api/external/v1/contexts/'+ident+'/resource?expected_revision=1',headers=h).status_code==200
    assert c.put(path,headers=a,json=body).status_code==409
    heartbeat={**body,'revision':3}
    assert c.put(path,headers=a,json=heartbeat).status_code==200
    assert c.get('/api/external/v1/contexts/'+ident+'/resource?expected_revision=1',headers=h).status_code==200
    app.state.db.execute('UPDATE workspace_contexts SET expires_at=0 WHERE id=?',(ident,));app.state.db.commit()
    assert c.get('/api/external/v1/contexts/'+ident,headers=h).status_code==409
    body['revision']=4;assert c.put(path,headers=a,json=body).status_code==200
    assert c.post('/api/auth/logout',headers=a).status_code==200
    assert c.get('/api/external/v1/contexts/'+ident,headers=h).status_code==404


def test_shared_selection_and_local_result_projection_idempotent(secured):
    c,app=secured;a,d,text=setup(c,app)
    anchor={'paper_id':1,'file_version':d['file_version'],'page':1,'quote':text,'rects':[]}
    located=c.post('/api/reader/anchors/locate',headers=a,json=anchor);assert located.status_code==200,located.text
    assert located.json()['status']=='located'
    ident=c.post('/api/workbench/contexts',headers=a).json()['id']
    state={'workspace_id':'b'*32,'revision':1,'view':'reader','resource':{'paper_id':1,'file_hash':d['file_version']},'page':1,'shared':True}
    assert c.put('/api/workbench/contexts/'+ident,headers=a,json=state).status_code==200
    selection=c.post('/api/workbench/contexts/'+ident+'/selections',headers=a,json=anchor);assert selection.status_code==201,selection.text
    _,h=token(c,a,['context:read','context:selection','papers:read','artifacts:read','artifacts:write','annotations:write'],[1])
    assert c.get('/api/external/v1/selections/'+selection.json()['id'],headers=h).status_code==200
    payload={'client_job_id':'local-reading-1','artifact':{'title':'Local guide','kind':'guide','markdown':'# Local summary','paper_ids':[1],'status':'complete'},'annotations':[{**anchor,'kind':'highlight','rects':located.json()['rects'],'content':'Important idea'}],'translation':anchor,'declared_skill':'my-local-reader'}
    headers={**h,'Idempotency-Key':'sync-one'}
    r=c.post('/api/external/v1/research-submissions',headers=headers,json=payload);assert r.status_code==201,r.text
    receipt=r.json();assert receipt['origin']=='external' and not receipt['model_called']
    assert c.post('/api/external/v1/research-submissions',headers=headers,json=payload).json()==receipt
    assert c.post('/api/external/v1/research-submissions',headers={**h,'Idempotency-Key':'same-job'},json=payload).json()==receipt
    assert c.get('/api/external/v1/research-submissions/local-reading-1',headers=h).json()==receipt
    notes=c.get('/api/reader/papers/1/annotations',headers=a).json()['annotations'];assert len(notes)==1 and notes[0]['origin']=='ai'
    assert c.post('/api/reader/annotations/'+notes[0]['id']+'/adopt',headers=a).status_code==201
    translations=c.get('/api/reader/papers/1/translations',headers=a).json()['translations'];assert len(translations)==1 and translations[0]['rects']
    tid=translations[0]['id'];assert c.patch('/api/reader/translations/'+tid,headers=a,json={'deleted':True}).status_code==200
    assert c.get('/api/reader/papers/1/translations',headers=a).json()['translations']==[]
    assert app.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0
    payload['artifact']['markdown']='Changed'
    assert c.post('/api/external/v1/research-submissions',headers={**h,'Idempotency-Key':'conflict-job'},json=payload).status_code==409


def test_context_rejects_other_resources_and_undeclared_fields(secured):
    c,app=secured;a,d,_=setup(c,app);ident=c.post('/api/workbench/contexts',headers=a).json()['id']
    base={'workspace_id':'c'*32,'revision':1,'view':'reader','resource':{'paper_id':999},'shared':True}
    assert c.put('/api/workbench/contexts/'+ident,headers=a,json=base).status_code==404
    assert c.put('/api/workbench/contexts/'+ident,headers=a,json={**base,'draft':'private'}).status_code==422
    other,account,_=user(c,app)
    assert c.put('/api/workbench/contexts/'+ident,headers=other,json=base).status_code==404


def test_local_stdio_mcp_reads_and_syncs_through_real_authorized_api(secured,tmp_path):
    import http.server,threading,subprocess,sys,os
    from pathlib import Path
    c,app=secured;a,d,text=setup(c,app)
    _,h=token(c,a,['papers:read','files:read','artifacts:read','artifacts:write'])
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def perform(self):
            data=self.rfile.read(int(self.headers.get('content-length','0')))
            result=c.request(self.command,self.path,headers={'Authorization':self.headers.get('Authorization',''),'Content-Type':self.headers.get('Content-Type','application/json'),'Idempotency-Key':self.headers.get('Idempotency-Key','')},content=data)
            self.send_response(result.status_code);self.send_header('Content-Length',str(len(result.content)));self.send_header('Content-Type',result.headers.get('content-type','application/json'));self.end_headers();self.wfile.write(result.content)
        do_GET=perform;do_POST=perform;do_PATCH=perform
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    key=tmp_path/'key';key.write_text(h['Authorization'][7:]);key.chmod(0o600);root=tmp_path/'research';root.mkdir();(root/'notes.md').write_text('# Local file')
    messages=[{'id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}}, {'id':2,'method':'tools/call','params':{'name':'firework_get_paper','arguments':{'paper_id':1}}}, {'id':3,'method':'tools/call','params':{'name':'firework_upload_file','arguments':{'paper_id':1,'file_path':str(root/'notes.md')}}}, {'id':4,'method':'tools/call','params':{'name':'firework_submit_research','arguments':{'request_key':'stdio-job','body':{'client_job_id':'stdio-job','artifact':{'title':'Local stdio guide','kind':'guide','markdown':'# Summary','paper_ids':[1],'status':'complete'}}}}}, {'id':5,'method':'tools/call','params':{'name':'firework_sync_receipt','arguments':{'client_job_id':'stdio-job'}}}]
    script=Path(__file__).resolve().parents[1]/'plugins/agent-skill/firework-paper-ops/scripts/firework_mcp.py'
    try:
        r=subprocess.run([sys.executable,str(script)],input='\n'.join(json.dumps({'jsonrpc':'2.0',**m}) for m in messages)+'\n',text=True,capture_output=True,timeout=15,env={**os.environ,'FIREWORK_URL':f'http://127.0.0.1:{server.server_port}','FIREWORK_ALLOW_LOCAL_HTTP':'1','FIREWORK_TOKEN_FILE':str(key),'FIREWORK_UPLOAD_ROOT':str(root)})
        assert r.returncode==0,r.stderr
        results=[json.loads(line) for line in r.stdout.splitlines()]
        assert all(not x.get('result',{}).get('isError') for x in results),json.dumps(results,ensure_ascii=False,indent=2)
        receipt=results[3]['result']['structuredContent'];assert receipt==results[4]['result']['structuredContent'] and not receipt['model_called']
        assert app.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0
    finally:server.shutdown();server.server_close()
