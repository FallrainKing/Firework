"""No inference: revisioned budgets, account isolation and CLI enforcement."""
import json
import pytest
from pydantic import ValidationError
from app.core.db import get_conn
from app.core.config import Settings
from app.core.errors import ServiceError
from app.runner_config import budgets as b
from app.agent import diagnostics
from agent_runner import cli
from test_auth_accounts import secured,login,user

@pytest.fixture
def db(tmp_path):
    conn=get_conn(Settings(data_dir=tmp_path,qdrant_url='unused'))
    yield conn
    conn.close()

def test_snapshot_revisions_and_tool_permissions(db):
    assert b.listing(db)['default_budget_id'] is None
    p={'id':'chat','tools':['paper_read'],'max_calls':1,'max_turns':6,'max_budget_usd':.2}
    assert b.resolve(db,p)['max_budget_usd']==.2
    saved=b.save(db,b.BudgetWrite(name='Mine',values=b.BudgetValues()))
    ref=b.BudgetRef(id=saved['id'],revision=1)
    frozen=b.resolve(db,p,ref)
    assert frozen['tools']==['paper_read'] and frozen['max_budget_usd'] is None
    b.save(db,b.BudgetWrite(name='New',values=b.BudgetValues(max_turns=30),expected_revision=1),saved['id'])
    assert frozen['budget_snapshot']['max_turns']==24
    with pytest.raises(ServiceError):b.resolve(db,p,ref)
    assert db.execute('SELECT count(*) FROM runner_budget_revisions WHERE budget_id=?',(ref.id,)).fetchone()[0]==2
    with pytest.raises(ServiceError):b.save(db,b.BudgetWrite(name='No',values=b.BudgetValues(),expected_revision=1),'standard')

def test_default_and_structured_skill_validation(db):
    b.set_default(db,b.DefaultWrite(budget_id='standard',expected_revision=1))
    guide={'id':'paper_guide','tools':['reader_guide_context','reader_guide_material','reader_guide_submit']}
    assert b.resolve(db,guide)['max_output_tokens']==8192
    with pytest.raises(ServiceError):b.resolve(db,guide,b.BudgetRef(id='quick',revision=1))
    with pytest.raises(ServiceError):b.set_default(db,b.DefaultWrite(budget_id=None,expected_revision=1))

@pytest.mark.parametrize('values',[{'timeout_s':0},{'max_calls':101},{'max_budget_usd':float('nan')},{'cost_mode':'cli_estimate_guard'},{'max_budget_usd':.2},{'tools':['shell']},{'max_turns':101}])
def test_invalid(values):
    with pytest.raises(ValidationError):b.BudgetValues(**values)

def test_cli_budget_is_optional_and_failures_explained():
    policy={'max_turns':24,'max_budget_usd':None,'tools':['paper_read']}
    args=cli.build_args(policy,'model','sid',False,{},'skill',False)
    assert '--max-budget-usd' not in args
    assert 'mcp__research__paper_read' in args
    policy['max_budget_usd']=.2
    args=cli.build_args(policy,'model','sid',False,{},'skill',False)
    assert args[args.index('--max-budget-usd')+1]=='0.2'
    v=diagnostics.view({'status':'failed','answer':'partial','metadata_json':json.dumps({'subtype':'error_max_budget_usd'}),'execution_policy_json':'{}'})
    assert v['finish_reason']=='budget_usd' and v['partial_available'] and not v['cost_verified']

def test_web_configuration_is_account_scoped(secured):
    c,app=secured
    a=login(c)
    assert c.get('/api/me/runner/budgets').status_code==401
    assert c.post('/api/me/runner/budgets',headers={'Cookie':a['Cookie']},json={'name':'x','values':{}}).status_code==403
    made=c.post('/api/me/runner/budgets',headers=a,json={'name':'admin-only','values':{}})
    assert made.status_code==201,made.text
    other,account,a=user(c,app)
    mine=c.get('/api/me/runner/budgets',headers=other).json()
    assert made.json()['id'] not in [x['id'] for x in mine['budgets']]
    assert c.put('/api/me/runner/budgets/default',headers=other,json={'budget_id':made.json()['id'],'expected_revision':1}).status_code==404
    preview=c.post('/api/me/runner/budgets/preflight',headers=other,json={'skill':'paper_guide','budget':{'id':'standard','revision':1}})
    assert preview.status_code==200,preview.text
    assert preview.json()['effective']['max_budget_usd'] is None
    assert preview.json()['tools']==['reader_guide_context','reader_guide_material','reader_guide_submit','skill_resource']
    assert c.post('/api/me/runner/budgets/preflight',headers=other,json={'skill':'paper_guide','budget':{'id':'quick','revision':1}}).status_code==422

from test_agent_mvp import client,wait,runner_mock,CANNED_RESULT
from app.agent import runner_client
from app.agent.protocol import RUNNER_PROTOCOL_VERSION
import httpx

def test_run_budget_frozen_and_forwarded(client,monkeypatch):
    c,settings=client
    captured=[]
    base=runner_mock(CANNED_RESULT,capture=captured)
    async def transport(req):
        if req.url.path=='/health':return httpx.Response(200,json={'status':'ok','protocol_version':RUNNER_PROTOCOL_VERSION})
        return await base(req)
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(transport),base_url='http://test'))
    body={'prompt':'hello','request_key':'budget-run','budget':{'id':'standard','revision':1}}
    r=c.post('/api/agent/runs',json=body)
    assert r.status_code==202,r.text
    done=wait(c,r.json()['id'])
    assert done['status']=='succeeded'
    assert done['diagnostics']['budget_snapshot']['max_budget_usd'] is None
    assert captured[0]['budget_policy']['max_turns']==24
    assert c.post('/api/agent/runs',json=body).json()['id']==done['id']
    assert c.post('/api/agent/runs',json={**body,'budget':{'id':'deep','revision':1}}).status_code==409
    assert len(captured)==1

def test_old_runner_never_receives_budget_run(client,monkeypatch):
    c,_=client
    posts=[]
    async def transport(req):
        if req.method=='POST':posts.append(req.url.path)
        return httpx.Response(200,json={'status':'ok','protocol_version':5})
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(transport),base_url='http://test'))
    r=c.post('/api/agent/runs',json={'prompt':'test','budget':{'id':'standard','revision':1}})
    assert r.status_code==202,r.text
    done=wait(c,r.json()['id'])
    assert done['status']=='failed' and done['diagnostics']['finish_reason']=='runner_protocol_mismatch'
    assert posts==[]
