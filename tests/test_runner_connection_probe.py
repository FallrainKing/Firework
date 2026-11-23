from test_auth_accounts import secured

import asyncio,httpx,json
from agent_runner.connection_probe import probe

def test_probe_never_equates_reachable_with_valid_auth(monkeypatch):
    from agent_runner import connection_probe
    monkeypatch.setattr(connection_probe,'validate_destination',lambda _:None)
    seen=[]
    def factory(**kwargs):
        async def response(req):seen.append(req);return httpx.Response(401)
        return httpx.AsyncClient(transport=httpx.MockTransport(response))
    snap={'base_url':'https://example.org','auth_type':'api_key','model':'test'}
    result=asyncio.run(probe(snap,'private-key','network',factory));assert result['status']=='reachable' and not result['model_called']
    assert 'x-api-key' not in seen[0].headers
    result=asyncio.run(probe(snap,'private-key','model',factory));assert result['reason']=='authentication'
    assert 'private-key' not in str(result)

def test_model_probe_requires_real_text_and_stream_finish(monkeypatch):
    from agent_runner import connection_probe
    monkeypatch.setattr(connection_probe,'validate_destination',lambda _:None)
    def factory(**kwargs):
        def response(req):
            assert json.loads(req.content)['max_tokens']==32
            return httpx.Response(200,text='data: '+json.dumps({'type':'content_block_delta','delta':{'text':'OK'}})+'\n\ndata: {"type":"message_stop"}\n\n')
        return httpx.AsyncClient(transport=httpx.MockTransport(response))
    snap={'base_url':'https://example.org','auth_type':'bearer','model':'test'}
    assert asyncio.run(probe(snap,'private-key','model',factory))['status']=='passed'


def test_web_probe_requires_confirmation_and_keeps_connection_revision(secured,monkeypatch):
    import time
    from test_auth_accounts import login
    from app.agent import runner_client
    from test_runner_connections import CONFIG,FAKE
    c,app=secured;a=login(c)
    made=c.post('/api/me/runner/connections',headers=a,json={'name':'test','config':CONFIG,'api_key':FAKE}).json();seen=[]
    async def response(req):
        seen.append(json.loads(req.content));return httpx.Response(200,json={'status':'passed','model_called':True,'stream_verified':True})
    monkeypatch.setattr(runner_client,'client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(response),base_url='http://runner'))
    path='/api/me/runner/connections/'+made['id']+'/tests'
    assert c.post(path,headers=a,json={'kind':'model','expected_revision':1}).status_code==422
    r=c.post(path,headers=a,json={'kind':'model','expected_revision':1,'confirmed':True});assert r.status_code==202,r.text
    tid=r.json()['id']
    for _ in range(50):
        test=c.get('/api/me/runner/connections/tests/'+tid,headers=a).json()
        if test['status']!='running':break
        time.sleep(.01)
    assert test['status']=='passed' and seen[0]['connection_snapshot']['model']==CONFIG['model']
    assert FAKE not in json.dumps(test)
    c.patch('/api/me/runner/connections/'+made['id'],headers=a,json={'name':'changed','config':CONFIG,'expected_revision':1})
    assert c.get('/api/me/runner/connections/tests/'+tid,headers=a).json()['stale']
