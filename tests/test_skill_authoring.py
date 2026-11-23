import json
from test_auth_accounts import secured,login,user
from app.skills import service

def body(**kw):return {'name':'Custom research','description':'Test','version':'1.0.0','instructions':'Explain only verified material.','tools':['paper_page'],'resources':{'references/rules.md':'Use actual pages.'},'surfaces':['reader_chat'],**kw}

def test_editor_publication_and_feature_scope(secured):
    c,app=secured;a=login(c)
    r=c.post('/api/skills/drafts',headers=a,json=body());assert r.status_code==201,r.text
    d=r.json();sid=d['skill_id'];assert d['revision']==1
    assert c.get('/api/skills/available?surface=reader_chat',headers=a).status_code==200
    r=c.post('/api/skills/'+sid+'/publish',headers=a,json={'expected_revision':1});assert r.status_code==200,r.text
    assert r.json()['name']=='Custom research' and r.json()['status']=='disabled'
    assert c.post('/api/skills/'+sid+'/enable',headers=a).status_code==200
    choices=c.get('/api/skills/available?surface=reader_chat',headers=a).json()['skills'];assert next(s for s in choices if s['id']==sid)['selectable']
    assert sid not in [s['id'] for s in c.get('/api/skills/available?surface=frontier',headers=a).json()['skills']]
    assert c.post('/api/skills/'+sid+'/publish',headers=a,json={'expected_revision':1}).status_code==200
    v=r.json()['default_version_id']
    assert c.patch('/api/skills/'+sid+'/draft',headers=a,json={**body(version='2.0.0',instructions='New instruction'),'expected_revision':1}).status_code==200
    assert c.patch('/api/skills/'+sid+'/draft',headers=a,json={**body(),'expected_revision':1}).status_code==409
    assert c.get('/api/skills/'+sid,headers=a).json()['default_version_id']==v
    renamed=c.patch('/api/skills/'+sid,headers=a,json={'name':'显示名'});assert renamed.status_code==200
    assert renamed.json()['id']==sid
    assert app.state.db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==0

def test_account_isolation_paths_and_scope_revision(secured):
    c,app=secured;a=login(c)
    for path in ('','../outside.md','/tmp/private.md','references/../../bad.md','SKILL.md','references/x.py'):
        assert c.post('/api/skills/drafts',headers=a,json=body(resources={path:'bad'})).status_code==422
    d=c.post('/api/skills/drafts',headers=a,json=body()).json();sid=d['skill_id']
    assert c.put('/api/skills/'+sid+'/placements',headers=a,json={'surfaces':['reader_chat'],'expected_revision':0}).status_code==200
    assert c.put('/api/skills/'+sid+'/placements',headers=a,json={'surfaces':[],'expected_revision':0}).status_code==409
    other,_,a=user(c,app)
    assert c.get('/api/skills/'+sid+'/draft',headers=other).status_code==404
    assert c.post('/api/skills/'+sid+'/publish',headers=other,json={'expected_revision':1}).status_code==404

def test_version_cannot_belong_to_another_skill(secured):
    c,app=secured;a=login(c);service.ensure_builtin_skills(app.state.db)
    v=service.execution_policy(app.state.db,'paper_read')['version_id']
    import pytest
    with pytest.raises(ValueError):service.execution_policy(app.state.db,'chat',v)


def test_existing_package_can_start_an_online_draft(secured):
    c,app=secured;a=login(c)
    d=c.post('/api/skills/drafts',headers=a,json=body()).json();sid=d['skill_id']
    assert c.post('/api/skills/'+sid+'/publish',headers=a,json={'expected_revision':1}).status_code==200
    app.state.db.execute('DELETE FROM skill_drafts WHERE skill_id=?',(sid,));app.state.db.commit()
    initial=c.get('/api/skills/'+sid+'/draft',headers=a).json()
    assert initial['revision']==0
    response=c.patch('/api/skills/'+sid+'/draft',headers=a,json={**initial['body'],'expected_revision':0})
    assert response.status_code==200,response.text


def test_structured_task_skill_cannot_run_as_general_chat(secured):
    c,app=secured;a=login(c)
    r=c.post('/api/sessions',headers=a,json={'template_id':'chat','skill_id':'frontier_monitor','entry_context':'research_chat'})
    assert r.status_code==409
    assert c.post('/api/sessions',headers=a,json={'template_id':'chat','entry_context':'frontier'}).status_code==422


def test_builtin_instructions_are_loaded_for_an_editable_copy(secured):
    c,app=secured;a=login(c)
    c.get('/api/skills',headers=a)
    for sid in ('paper_read','frontier_monitor','paper_guide'):
        r=c.get('/api/skills/'+sid+'/draft',headers=a)
        assert r.status_code==200,r.text
        assert len(r.json()['body']['instructions'])>100
