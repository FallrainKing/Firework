"""Native model relay restrictions without external traffic or paid inference."""
import asyncio
import httpx
from agent_runner.model_bridge import ModelBridge
from agent_runner.terminal import container_args


def test_native_docker_isolation(tmp_path,monkeypatch):
    from agent_runner import cli
    monkeypatch.setattr(cli,'binary_path',lambda:tmp_path/'claude')
    args=container_args(tmp_path,'test-native','test-session','test-model','relay-only',False)
    joined=' '.join(args)
    for flag in ['--network none','--read-only','--cap-drop=ALL','no-new-privileges','--pids-limit 128','--memory 2g','dst=/papers,readonly']:
        assert flag in joined
    assert 'docker.sock' not in joined and 'app.db' not in joined
    assert '--env ANTHROPIC_API_KEY=relay-only' in joined


def test_relay_rejects_unauthorized_unarmed_model_and_destinations(tmp_path,monkeypatch):
    async def run():
        from agent_runner import model_bridge
        monkeypatch.setattr(model_bridge,'validate_destination',lambda _:None)
        relay=ModelBridge(tmp_path,'https://example.org','private-secret','api_key','test-model','relay-token')
        sent=[]
        async def upstream(req):
            sent.append(req)
            assert req.headers['x-api-key']=='private-secret'
            assert 'relay-token' not in str(req.headers)
            return httpx.Response(200,content=b'ordinary result')
        await relay.client.aclose();relay.client=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=relay.app),base_url='http://relay') as c:
            headers={'x-api-key':'relay-token'};body={'model':'test-model','messages':[]}
            assert (await c.post('/v1/messages',json=body)).status_code==401
            assert (await c.post('/v1/messages',headers=headers,json=body)).status_code==403
            relay.armed=True
            assert (await c.post('/v1/messages',headers=headers,json={**body,'model':'other'})).status_code==409
            for path in ['/admin','/v1/messages?url=http://localhost','/v1/models/../../secrets']:
                assert (await c.post(path,headers=headers,json=body)).status_code==403
            assert not sent
            assert (await c.post('/v1/messages',headers=headers,json=body)).content==b'ordinary result'
            relay.authorize=lambda:False
            assert (await c.post('/v1/messages',headers=headers,json=body)).status_code==403
            assert len(sent)==1
        await relay.close()
    asyncio.run(run())


def test_relay_redacts_credentials_and_refuses_redirects(tmp_path,monkeypatch):
    class Fragments(httpx.AsyncByteStream):
        async def __aiter__(self):
            for part in [b'prefix priv',b'ate-',b'secret suffix private-secret']:yield part
    async def run():
        from agent_runner import model_bridge
        monkeypatch.setattr(model_bridge,'validate_destination',lambda _:None)
        relay=ModelBridge(tmp_path,'https://example.org','private-secret','api_key','test-model','relay-token');relay.armed=True
        await relay.client.aclose()
        relay.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=Fragments())))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=relay.app),base_url='http://relay') as c:
            r=await c.post('/v1/messages',headers={'x-api-key':'relay-token'},json={'model':'test-model'})
            assert r.content==b'prefix [REDACTED] suffix [REDACTED]'
            await relay.client.aclose();relay.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(302,headers={'location':'https://evil.invalid'})))
            r=await c.post('/v1/messages',headers={'x-api-key':'relay-token'},json={'model':'test-model'});assert r.status_code==502
        await relay.close()
    asyncio.run(run())


def test_terminal_run_control_idempotency_and_cleanup(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import os
    import pytest
    from fastapi import HTTPException
    from app.core.config import Settings
    from app.core.db import get_conn
    from app.sessions import repository
    from agent_runner import terminal
    settings=Settings(data_dir=tmp_path,qdrant_url=':memory:');db=get_conn(settings)
    with db:
        sid=repository.insert_session(db,title='Terminal',kind='chat',skill='chat',template_id=None,category_id=None,native_session_id='11111111-1111-4111-8111-111111111111',draft_prompt='').lastrowid
        db.execute("UPDATE conversations SET execution_mode='terminal',runner_connection_json='{}' WHERE id=?",(sid,))
        db.execute('INSERT INTO native_terminals(conversation_id) VALUES (?)',(sid,))
    db.close()
    async def run():
        done=asyncio.Event();fds=[]
        class Bridge:
            def __init__(self,*args):self.model='test-model';self.message_calls=0;self.armed=False;self.authorize=lambda:True;self.closed=False
            async def start(self):pass
            async def close(self):self.closed=True
        class Process:
            returncode=0
            async def wait(self):await done.wait();return 0
        async def spawn(*args,**kwargs):fds.append(os.dup(kwargs['stdin']));return Process()
        async def command(*args,**kwargs):
            done.set()
            for fd in fds:os.close(fd)
            fds.clear()
            return b''
        async def available():return {'available':True}
        monkeypatch.setattr(terminal,'availability',available);monkeypatch.setattr(terminal,'ModelBridge',Bridge)
        monkeypatch.setattr(terminal.asyncio,'create_subprocess_exec',spawn);monkeypatch.setattr(terminal,'command',command)
        engine=SimpleNamespace(runtime=tmp_path/'agent',_sem=asyncio.Semaphore(1),_env_loader=lambda _: {'ANTHROPIC_API_KEY':'not-real','ANTHROPIC_MODEL':'test-model'})
        manager=terminal.TerminalManager(engine)
        body={'controller_id':'a'*32}
        frame=await manager.start(sid,body,True);assert frame['state']=='running'
        same=await manager.start(sid,body,True);assert frame['generation']==same['generation']
        with pytest.raises(HTTPException) as e:await manager.start(sid,{'controller_id':'b'*32},True)
        assert e.value.status_code==409
        request={'generation':frame['generation'],'controller_id':'a'*32,'request_key':'c'*32,'data':'hello'}
        assert (await manager.input(sid,request))['accepted']
        assert (await manager.input(sid,request))['reused']
        with pytest.raises(HTTPException):await manager.input(sid,{**request,'data':'different'})
        await manager.stop(sid,frame['generation'],controller_id='a'*32)
        await asyncio.wait_for(manager.items[sid]['pump'],2)
        assert engine._sem._value==1 and manager.items[sid]['relay'].closed
        with terminal.database(engine.runtime) as check:
            row=check.execute('SELECT status FROM agent_runs WHERE id=?',(frame['run_id'],)).fetchone()
            assert row['status']=='cancelled'
            assert check.execute("SELECT count(*) FROM run_events WHERE run_id=? AND kind='native_input'",(frame['run_id'],)).fetchone()[0]==1
    asyncio.run(run())


def test_real_cli_beta_query_is_explicitly_supported(tmp_path,monkeypatch):
    async def run():
        from agent_runner import model_bridge
        monkeypatch.setattr(model_bridge,'validate_destination',lambda _:None)
        bridge=ModelBridge(tmp_path,'https://example.org','secret','api_key','model[1M]','relay');bridge.armed=True
        await bridge.client.aclose();seen=[]
        def response(request):seen.append(str(request.url));return httpx.Response(200,json={'ok':True})
        bridge.client=httpx.AsyncClient(transport=httpx.MockTransport(response))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge.app),base_url='http://relay') as c:
            r=await c.post('/v1/messages?beta=true',headers={'x-api-key':'relay'},json={'model':'model'})
            assert r.status_code==200 and seen==['https://example.org/v1/messages?beta=true']
            r=await c.post('/v1/messages?beta=true&url=http://localhost',headers={'x-api-key':'relay'},json={'model':'model'})
            assert r.status_code==403 and len(seen)==1
        await bridge.close()
    asyncio.run(run())
