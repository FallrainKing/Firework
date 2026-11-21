"""Real API + per-account SQLite/files/Qdrant; no network models or paid runs."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import json
import sqlite3
from types import SimpleNamespace
import uuid
import io
import zipfile
import pymupdf
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from app.auth.store import AuthStore,COOKIE,password_hash,verify_password
from app.auth.runtime import WorkspaceManager
from app.core.config import Settings
from app.core.db import get_conn
from app.main import create_app
from app.agent.service import init_agent_state
from app.rag.vector_store import VectorStore,ChunkPoint

ADMIN_PASSWORD='Existing-Admin-Password-123'
USER_PASSWORD='Separate-Research-Password-123'

@pytest.fixture
def secured(tmp_path):
    app=create_app()
    settings=Settings(data_dir=tmp_path/'data',qdrant_url=':memory:')
    app.state.settings=settings;app.state.db=get_conn(settings)
    app.state.store=VectorStore(QdrantClient(':memory:'));app.state.store.ensure_collection(4)
    app.state.embedder=SimpleNamespace(dimension=4)
    app.state.auth_store=AuthStore(settings.data_dir,secure_cookie=False,public_origin='http://testserver')
    app.state.auth_store.bootstrap('paper',ADMIN_PASSWORD)
    app.state.workspaces=WorkspaceManager(app)
    init_agent_state(app)
    @asynccontextmanager
    async def lifecycle(a):
        yield
        await a.state.workspaces.close()
        a.state.db.close();a.state.auth_store.close();a.state.store._client.close()
    app.router.lifespan_context=lifecycle
    with TestClient(app) as client:yield client,app


def login(c,name='paper',password=ADMIN_PASSWORD):
    c.cookies.clear()
    r=c.post('/api/auth/login',json={'username':name,'password':password})
    assert r.status_code==200,r.text
    cookie=c.app.state.auth_store.cookie_name
    token=c.cookies.get(cookie);c.cookies.clear()
    return {'Cookie':cookie+'='+token,'X-CSRF-Token':r.json()['csrf_token']}


def user(c,app,name='reader-one'):
    admin=login(c)
    r=c.post('/api/admin/accounts',headers=admin,json={'username':name,'password':USER_PASSWORD})
    assert r.status_code==201,r.text
    ident=r.json()['id']
    assert not r.json()['enabled'] and not r.json()['login_allowed']
    assert c.patch('/api/admin/accounts/'+ident,headers=admin,json={'enabled':True}).status_code==200
    app.state.auth_store.admin_only=False  # tests exercise future enabled-account mode explicitly
    return login(c,name,USER_PASSWORD),app.state.auth_store.account(ident),admin


def run_async(c,coro):return c.portal.call(lambda:coro)


def paper(state,title='Private Alpha'):
    folder=state.settings.data_dir/'papers';folder.mkdir(exist_ok=True)
    path=folder/'one.pdf';d=pymupdf.open();p=d.new_page();p.insert_text((72,72),title);d.save(path);d.close()
    state.db.execute('INSERT INTO papers(id,title,pdf_path,authors) VALUES (1,?,?,?)',(title,str(path),'[]'));state.db.commit()


def test_password_hash_is_salted_and_not_plaintext():
    a=password_hash(ADMIN_PASSWORD);b=password_hash(ADMIN_PASSWORD)
    assert a!=b and ADMIN_PASSWORD not in a
    assert verify_password(ADMIN_PASSWORD,a) and not verify_password('wrong',a)


def test_every_registered_private_route_fails_closed(secured):
    c,app=secured
    import re
    for path,operations in app.openapi()['paths'].items():
        if not path.startswith('/api/') or path in ('/api/auth/login','/api/auth/register','/api/auth/session'):continue
        concrete=re.sub(r'\{[^}]+\}','1',path)
        for method in operations:
            r=c.request(method,concrete)
            assert r.status_code in (401,403),(method,path,r.status_code)
    assert c.get('/openapi.json').status_code==401
    assert c.get('/health').status_code==200
    assert c.get('/api/auth/session').json()['authenticated'] is False


def test_registration_is_closed_and_only_original_admin_can_login(secured):
    c,app=secured;admin=login(c)
    assert c.post('/api/auth/register',json={'username':'someone','password':USER_PASSWORD}).status_code==403
    r=c.post('/api/admin/accounts',headers=admin,json={'username':'reader-one','password':USER_PASSWORD});assert r.status_code==201
    c.patch('/api/admin/accounts/'+r.json()['id'],headers=admin,json={'enabled':True})
    assert c.post('/api/auth/login',json={'username':'reader-one','password':USER_PASSWORD}).status_code==401
    assert c.patch('/api/admin/accounts/'+app.state.auth_store.primary_id(),headers=admin,json={'enabled':False}).status_code==409
    assert c.get('/api/me',headers=admin).json()['auth_mode']=='account'


def test_cookie_csrf_origin_and_logout(secured):
    c,app=secured
    app.state.auth_store.secure_cookie=True
    r=c.post('/api/auth/login',json={'username':'paper','password':ADMIN_PASSWORD})
    info=c.get('/api/auth/session').json();assert info['secure_cookie'] is True
    assert info['login_url']==app.state.auth_store.public_origin+'/#/login'
    cookie=r.headers['set-cookie'];assert all(v in cookie for v in ('HttpOnly','Secure','SameSite=strict','Path=/'))
    headers={'Cookie':COOKIE+'='+c.cookies.get(COOKIE),'X-CSRF-Token':r.json()['csrf_token']};c.cookies.clear()
    assert c.patch('/api/me',headers={'Cookie':headers['Cookie']},json={'display_name':'Blocked'}).status_code==403
    assert c.patch('/api/me',headers={**headers,'Origin':'https://evil.example'},json={'display_name':'Blocked'}).status_code==403
    assert c.patch('/api/me',headers=headers,json={'display_name':'Admin'}).status_code==200
    assert c.get('/api/library/papers',headers=headers).headers['cache-control']=='no-store'
    assert c.post('/api/auth/logout',headers=headers).status_code==200
    assert c.get('/api/library/papers',headers=headers).status_code==401
    assert c.post('/api/auth/login',headers={'Origin':'https://evil.example'},json={'username':'paper','password':ADMIN_PASSWORD}).status_code==403


def test_failed_login_throttle_persists_and_hides_identity(secured):
    c,app=secured
    for _ in range(10):assert c.post('/api/auth/login',json={'username':'unknown-user','password':'bad'}).status_code==401
    assert c.post('/api/auth/login',json={'username':'unknown-user','password':'bad'}).status_code==429
    assert app.state.auth_store.db.execute('SELECT count(*) FROM auth_attempts').fetchone()[0]==2


def test_password_change_revokes_all_browser_sessions(secured):
    c,app=secured;one=login(c);two=login(c)
    assert c.post('/api/auth/password',headers=one,json={'current_password':'wrong','new_password':USER_PASSWORD}).status_code==400
    assert c.post('/api/auth/password',headers=one,json={'current_password':ADMIN_PASSWORD,'new_password':USER_PASSWORD}).status_code==200
    for h in (one,two):assert c.get('/api/me',headers=h).status_code==401
    assert c.post('/api/auth/login',json={'username':'paper','password':ADMIN_PASSWORD}).status_code==401
    login(c,'paper',USER_PASSWORD)


def test_isolation_covers_identical_ids_files_search_notes_and_drafts(secured):
    c,app=secured;member,account,admin=user(c,app)
    a=app.state;b=run_async(c,app.state.workspaces.get(account['workspace_key']))
    paper(a,'Private Alpha');paper(b,'Private Beta')
    assert c.get('/api/library/papers',headers=admin).json()['papers'][0]['title']=='Private Alpha'
    assert c.get('/api/library/papers',headers=member).json()['papers'][0]['title']=='Private Beta'
    assert c.get('/api/library/papers',headers={**member,'X-Research-Workspace':'legacy'}).json()['papers'][0]['title']=='Private Beta'
    assert c.get('/api/library/papers?q=Alpha',headers=member).json()['total']==0
    assert c.get('/api/agent/library?q=Alpha',headers=member).json()['papers']==[]
    assert c.get('/api/reader/papers/1/file',headers=admin).content!=c.get('/api/reader/papers/1/file',headers=member).content
    sid=c.post('/api/sessions',headers=admin,json={'template_id':'read','paper_ids':[1]}).json()['session']['id']
    doc=c.get('/api/reader/papers/1',headers=admin).json()
    note=c.post('/api/reader/annotations',headers=admin,json={'paper_id':1,'page':1,'file_version':doc['file_version'],'kind':'note','content':'Secret Alpha','conversation_id':sid}).json()
    assert c.patch('/api/reader/annotations/'+note['id'],headers=member,json={'deleted':True}).status_code==404
    assert c.get('/api/reader/papers/1/annotations',headers=member).json()['annotations']==[]
    assert c.get('/api/sessions/'+str(sid),headers=member).status_code==404
    assert c.get('/api/workbench/drafts/'+str(sid)+'/1',headers=member).status_code in (400,404)
    assert c.get('/api/admin/accounts',headers=member).status_code==403
    assert c.get('/openapi.json',headers=member).status_code==403
    assert a.db.execute('SELECT title FROM papers WHERE id=1').fetchone()[0]=='Private Alpha'
    assert b.settings.data_dir!=a.settings.data_dir and b.settings.vector_collection!='chunks'


def test_cross_account_assets_and_run_ids_are_not_accessible(secured):
    c,app=secured;member,account,admin=user(c,app)
    paper(app.state)
    sid=c.post('/api/sessions',headers=admin,json={'template_id':'read','paper_ids':[1]}).json()['session']['id']
    rid=uuid.uuid4().hex
    app.state.db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status,answer) VALUES (?,?,?,'paper_read','secret','succeeded','secret answer')",(rid,rid,sid))
    iid=uuid.uuid4().hex
    app.state.db.execute("INSERT INTO import_requests(id,request_key,channel,source_value,status) VALUES (?,?,'doi','10.1/private','failed')",(iid,iid));app.state.db.commit()
    for path in ('/api/agent/runs/'+rid,'/api/agent/runs/'+rid+'/events','/api/imports/'+iid):assert c.get(path,headers=member).status_code==404
    assert c.post('/api/agent/runs/'+rid+'/cancel',headers=member).status_code==404
    assert c.post('/api/imports/'+iid+'/retry',headers=member).status_code==404
    from test_user_profile import PNG
    upload=c.post('/api/workbench/images',headers=admin,data={'conversation_id':sid,'paper_id':1},files={'file':('a.png',PNG,'image/png')});assert upload.status_code==201,upload.text
    image_id=upload.json()['id'];assert c.get('/api/workbench/images/'+image_id,headers=member).status_code==404
    avatar=c.post('/api/me/avatar',headers=admin,files={'avatar':('a.png',PNG,'image/png')}).json()['avatar_url']
    assert c.get(avatar,headers=member).status_code==404


def test_workspaces_frontier_skills_and_vectors_do_not_overlap(secured):
    c,app=secured;member,account,admin=user(c,app)
    aid='1'*32
    payload={'layout':{'left_width':235,'right_width':340,'left_hidden':False,'right_hidden':False},'tabs':[],'active_paper_id':None,'view':'library'}
    assert c.put('/api/workbench/states/'+aid,headers=admin,json=payload).status_code==200
    assert c.get('/api/workbench/states/'+aid,headers=member).json()['view']!='library'
    topic=c.post('/api/frontier/topics',headers=admin,json={'title':'Secret direction','config':{'keywords':['private topic']}});assert topic.status_code==201,topic.text
    assert c.get('/api/frontier/topics',headers=member).json()['topics']==[]
    assert c.post('/api/frontier/topics/'+str(topic.json()['id'])+'/runs',headers=member,json={'request_key':'cross-account'}).status_code==404
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('SKILL.md','# Private skill');z.writestr('skill.json',json.dumps({'slug':'private-skill','version':'1.0.0'}))
    imp=c.post('/api/skills/imports',headers=admin,files={'archive':('private.zip',archive.getvalue(),'application/zip')});assert imp.status_code==200,imp.text
    assert c.get('/api/skills/imports/'+imp.json()['import_id'],headers=member).status_code==404
    b=run_async(c,app.state.workspaces.get(account['workspace_key']))
    app.state.store.upsert_chunks([ChunkPoint(1,0,'Alpha secret',1,'Intro',[1.,0.,0.,0.])])
    b.store.upsert_chunks([ChunkPoint(1,0,'Beta private',1,'Intro',[1.,0.,0.,0.])])
    assert [r.text for r in app.state.store.search([1.,0.,0.,0.])]==['Alpha secret']
    assert [r.text for r in b.store.search([1.,0.,0.,0.])]==['Beta private']


def test_internal_callbacks_require_matching_workspace_token(secured):
    c,app=secured;member,account,admin=user(c,app)
    (app.state.settings.data_dir/'agent').mkdir(exist_ok=True)
    (app.state.settings.data_dir/'agent/internal-token').write_text('admin-private-token')
    b=run_async(c,app.state.workspaces.get(account['workspace_key']))
    (b.settings.data_dir/'agent').mkdir(exist_ok=True);(b.settings.data_dir/'agent/internal-token').write_text('member-private-token')
    headers={'X-Research-Workspace':account['workspace_key'],'X-Research-Tool-Token':'admin-private-token','X-Research-Run-Id':'1'*32}
    assert c.post('/api/internal/reader-guide/context',headers=headers,json={}).status_code==403
    assert c.post('/api/internal/reader-guide/context',headers={'X-Research-Workspace':'../legacy','X-Research-Tool-Token':'admin-private-token'},json={}).status_code==403
    assert c.post('/api/internal/reader-guide/context',headers={**headers,'X-Research-Tool-Token':'member-private-token'},json={}).status_code==403  # no matching active run either


def test_disable_revokes_sessions_without_deleting_account_data(secured):
    c,app=secured;member,account,admin=user(c,app)
    b=run_async(c,app.state.workspaces.get(account['workspace_key']));paper(b,'Keep private')
    r=c.patch('/api/admin/accounts/'+account['id'],headers=admin,json={'enabled':False});assert r.status_code==200
    assert c.get('/api/library/papers',headers=member).status_code==401
    assert b.db.execute('SELECT title FROM papers WHERE id=1').fetchone()[0]=='Keep private'


def test_unknown_auth_state_is_not_an_anonymous_bypass():
    c=TestClient(create_app())
    assert c.get('/api/library/papers').status_code==503


def test_agent_submission_uses_authenticated_workspace_not_client_header(secured,monkeypatch):
    import httpx
    from app.agent import runner_client
    from app.agent.protocol import RUNNER_PROTOCOL_VERSION
    c,app=secured;member,account,admin=user(c,app)
    configured=c.post('/api/me/runner/connections',headers=member,json={'name':'own-test','config':{'base_url':'https://api.example.com','model':'test'},'api_key':'test-only-key'})
    assert configured.status_code==201,configured.text
    assert c.put('/api/me/runner/connections/default',headers=member,json={'connection_id':configured.json()['id'],'expected_revision':1}).status_code==200
    captured=[]
    def handler(req):
        captured.append((req.method,req.url.path,req.headers.get('x-research-workspace')))
        if req.url.path=='/runs':return httpx.Response(202,json={'status':'queued'})
        if req.url.path.endswith('/events'):
            return httpx.Response(200,text='data: '+json.dumps({'type':'result','result':{'status':'succeeded','answer':'Only own account result','usage':{}}})+'\n\n')
        return httpx.Response(200,json={'status':'ok','protocol_version':RUNNER_PROTOCOL_VERSION})
    monkeypatch.setattr(runner_client.httpx,'AsyncHTTPTransport',lambda **kw:httpx.MockTransport(handler))
    r=c.post('/api/agent/runs',headers={**member,'X-Research-Workspace':'legacy'},json={'prompt':'Own account only','request_key':'same-key','workspace_key':'legacy'})
    assert r.status_code==202,r.text
    async def settle():await asyncio.gather(*list(app.state.workspaces.states[account['workspace_key']].agent_jobs))
    run_async(c,settle())
    assert captured and all(key==account['workspace_key'] for _,_,key in captured)
    assert c.get('/api/agent/runs/'+r.json()['id'],headers=admin).status_code==404
    assert c.get('/api/agent/runs/'+r.json()['id'],headers=member).json()['answer']=='Only own account result'


def test_auth_validation_does_not_echo_passwords(secured):
    c,_=secured
    password='Must-Not-Be-Echoed-'+('x'*300)
    r=c.post('/api/auth/login',json={'username':'paper','password':password})
    assert r.status_code==422 and 'Must-Not-Be-Echoed' not in r.text
    assert all('input' not in e for e in r.json()['detail'])


def test_maintenance_session_file_is_private_and_revocable(secured,tmp_path,monkeypatch,capsys):
    from app.auth.bootstrap import main
    c,app=secured;target=tmp_path/'session.json'
    monkeypatch.setenv('DATA_DIR',str(app.state.settings.data_dir))
    monkeypatch.setattr('sys.argv',['bootstrap','issue-session','--output',str(target),'--minutes','1'])
    main()
    saved=json.loads(target.read_text())
    assert target.stat().st_mode & 0o077==0
    assert app.state.auth_store.session(saved['token'])
    assert saved['token'] not in capsys.readouterr().out
    monkeypatch.setattr('sys.argv',['bootstrap','revoke-session','--input',str(target)])
    main()
    assert not target.exists() and app.state.auth_store.session(saved['token']) is None
    assert saved['token'] not in capsys.readouterr().out
