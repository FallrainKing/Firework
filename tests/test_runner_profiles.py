import json
import pytest
import httpx
from app.runner_config import profiles,budgets
from app.core.errors import ServiceError
from app.core.config import Settings
from app.core.db import get_conn
from app.skills import service as skills
from app.agent import runner_client
from app.agent.protocol import RUNNER_PROTOCOL_VERSION
from test_auth_accounts import secured,login,user
from test_agent_mvp import client,wait,runner_mock,CANNED_RESULT

def config(db,skill='chat'):
    skills.ensure_builtin_skills(db);budgets.ensure(db)
    p=skills.execution_policy(db,skill)
    return {'skill_id':skill,'skill_version_id':p['version_id'],'connection':None,'budget':{'id':'standard','revision':1},'role_prompt':'Use page evidence.','tools':[]}

def test_profile_permissions_revision_and_special_tasks(tmp_path):
    settings=Settings(data_dir=tmp_path,qdrant_url='unused');db=get_conn(settings)
    cfg=config(db)
    p=profiles.save(db,settings,profiles.ProfileWrite(name='Plan',config=cfg))
    ref=profiles.ProfileRef(id=p['id'],revision=1)
    assert profiles.resolve(db,settings,ref)['policy']['max_budget_usd'] is None
    for invalid in ({**cfg,'tools':['paper_import']},config(db,'paper_guide')):
        with pytest.raises(ServiceError):profiles.effective(db,settings,profiles.ProfileConfig(**invalid))
    profiles.save(db,settings,profiles.ProfileWrite(name='New',config=cfg,expected_revision=1),p['id'])
    with pytest.raises(ServiceError):profiles.resolve(db,settings,ref)
    db.close()

def test_profile_web_catalog_isolation(secured):
    c,app=secured;a=login(c);cfg=config(app.state.db)
    r=c.post('/api/me/runner/profiles',headers=a,json={'name':'Mine','config':cfg});assert r.status_code==201,r.text
    assert c.get('/api/me/runner/mcp',headers=a).json()['external_servers_enabled'] is False
    assert c.get('/api/me/runner/models',headers=a).json()['model_called'] is False
    other,_,a=user(c,app)
    assert c.get('/api/me/runner/profiles',headers=other).json()['profiles']==[]
    assert c.patch('/api/me/runner/profiles/'+r.json()['id'],headers=other,json={'name':'foreign','config':cfg,'enabled':False,'expected_revision':1}).status_code==409
    assert c.post('/api/me/runner/profiles/preflight',headers=other,json=cfg).status_code==409

def test_run_profile_bound_and_idempotent(client,monkeypatch):
    c,_=client;captured=[];base=runner_mock(CANNED_RESULT,capture=captured)
    async def transport(req):
        if req.url.path=='/health':return httpx.Response(200,json={'status':'ok','protocol_version':RUNNER_PROTOCOL_VERSION})
        return await base(req)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(transport),base_url='http://test'))
    from app.runner_config.profiles_router import router
    c.app.include_router(router)
    cfg=config(c.app.state.db);p=c.post('/api/me/runner/profiles',json={'name':'My plan','config':cfg})
    assert p.status_code==201,p.text
    ref={'id':p.json()['id'],'revision':1};body={'prompt':'test profile','request_key':'profile-first','profile':ref}
    r=c.post('/api/agent/runs',json=body);assert r.status_code==202,r.text
    done=wait(c,r.json()['id']);assert done['status']=='succeeded',done
    assert c.post('/api/agent/runs',json=body).json()['id']==done['id']
    assert captured[0]['profile_ref']==ref
    sid=done['conversation_id']
    assert c.post('/api/agent/runs',json={**body,'request_key':'bad','budget':{'id':'deep','revision':1},'conversation_id':sid}).status_code==422
    r=c.post('/api/agent/runs',json={'prompt':'continue','conversation_id':sid,'request_key':'profile-next'});assert r.status_code==202,r.text
    assert wait(c,r.json()['id'])['status']=='succeeded'
    assert captured[1]['profile_ref']==ref
    c.patch('/api/me/runner/profiles/'+ref['id'],json={'name':'revised','config':cfg,'expected_revision':1})
    assert c.post('/api/agent/runs',json={'prompt':'stale','conversation_id':sid}).status_code==409

from test_runner_jobs import engine,runtime,make_spawn,result_line,body
from agent_runner import jobs as jobs_mod,server
import asyncio

def test_runner_revalidates_plan_before_spawn(engine,runtime,monkeypatch):
    settings=Settings(data_dir=runtime.parent,qdrant_url='unused');db=get_conn(settings)
    p=profiles.save(db,settings,profiles.ProfileWrite(name='Plan',config=config(db)))
    ref=profiles.ProfileRef(id=p['id'],revision=1);plan=profiles.resolve(db,settings,ref)
    policy=plan['policy']|{'profile_snapshot':plan['snapshot'],'role_prompt':plan['role_prompt']}
    profiles.save(db,settings,profiles.ProfileWrite(name='Changed',config=config(db),expected_revision=1),p['id']);db.close()
    def forbidden(*args,**kwargs):raise AssertionError('stale profile must never spawn a model')
    monkeypatch.setattr(jobs_mod.asyncio,'create_subprocess_exec',forbidden)
    async def main():
        await engine.start();await engine.submit('e'*32,'chat',body(skill_policy=policy))
        result=[f async for f in engine.events('e'*32)][-1]['result']
        assert result['status']=='failed'
        await engine.close()
    asyncio.run(main())

def test_runner_narrows_cli_tools_and_applies_role(engine,runtime,monkeypatch):
    settings=Settings(data_dir=runtime.parent,qdrant_url='unused');db=get_conn(settings)
    p=profiles.save(db,settings,profiles.ProfileWrite(name='Plan',config=config(db)))
    plan=profiles.resolve(db,settings,profiles.ProfileRef(id=p['id'],revision=1));db.close()
    policy=plan['policy']|{'profile_snapshot':plan['snapshot'],'role_prompt':plan['role_prompt']};captured={}
    monkeypatch.setattr(jobs_mod.asyncio,'create_subprocess_exec',make_spawn([result_line('answer')],capture=captured))
    async def main():
        await engine.start();await engine.submit('f'*32,'chat',body(skill_policy=policy))
        result=[f async for f in engine.events('f'*32)][-1]['result'];assert result['status']=='succeeded',result
        assert 'Use page evidence.' in ' '.join(captured['args'])
        assert 'mcp__research__paper_import' not in ' '.join(captured['args'])
        await engine.close()
    asyncio.run(main())
