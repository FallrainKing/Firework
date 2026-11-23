"""HTTP routes for agent status and persisted runs."""
import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from . import service
from .schemas import RunCreate

router = APIRouter(prefix='/api/agent', tags=['agent'])


@router.get('/status')
async def status(request: Request):
    return await service.status_view(request.app.state.db)


@router.get('/runs')
async def list_runs(request: Request, conversation_id: int | None = None, q: str = Query('', max_length=200)):
    return service.list_runs(request.app.state.db, conversation_id, q)


@router.get('/runs/{run_id}')
async def get_run(run_id: str, request: Request):
    return service.get_run(request.app.state.db, run_id)


@router.post('/runs/{run_id}/cancel')
async def cancel_run(run_id: str, request: Request):
    return await service.cancel_run(request.app.state.db, run_id, request.app.state)


@router.get('/runs/{run_id}/events')
async def run_events(run_id: str, request: Request):
    """Browser-facing progress stream, tails the app's own database.

    Decoupled from the Runner connection: survives runner restarts and works
    for runs that finished long ago (first frame is the terminal state).
    """
    db = request.app.state.db
    if service.run_snapshot(db, run_id) is None:
        from ..core.errors import ServiceError
        raise ServiceError(404, 'Task not found')

    async def gen():
        last = None
        heartbeat=0
        while True:
            if await request.is_disconnected():return
            auth=getattr(request.app.state,"auth_store",None)
            if auth:
                from ..auth.store import COOKIE
                if auth.session(request.cookies.get(auth.cookie_name,"")) is None:
                    return
            snap = service.run_snapshot(db, run_id)
            if snap is None:
                return
            if snap != last:
                yield f'id: {run_id}:{snap["revision"]}\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n'
                last = snap
            if snap['status'] in ('succeeded', 'failed', 'cancelled'):
                return
            heartbeat+=1
            if heartbeat%30==0:yield ': heartbeat\n\n'
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no','Cache-Control':'no-store'})


@router.get('/library')
async def search_library(request: Request, q: str = Query('', max_length=200)):
    return service.search_library(request.app.state.db, q)


@router.post('/runs', status_code=202)
async def create_run(body: RunCreate, request: Request):
    return await service.create_run(body, request.app.state)


@router.get('/providers')
async def providers(request:Request):
    import httpx
    from . import runner_client
    from ..core.errors import ServiceError
    try:
        async with runner_client.client() as client:
            response=await client.get('/providers',timeout=8)
        if response.status_code!=200:raise ServiceError(503,'运行环境检测暂不可用，请检查 Runner 版本')
        return response.json()
    except (httpx.HTTPError,ValueError):raise ServiceError(503,'运行环境检测暂不可用') from None


@router.get('/runs/{run_id}/timeline')
async def timeline(run_id:str,request:Request,after:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200)):
    from ..research.events import listing
    return listing(request.app.state.db,run_id,after,limit)

@router.get('/runs/{run_id}/materials')
async def materials(run_id:str,request:Request):
    service.get_run(request.app.state.db,run_id)
    from ..research.materials import frozen
    return frozen(request.app.state.db,run_id)

@router.get('/runs/{run_id}/debug-bundle')
async def debug_bundle(run_id:str,request:Request):
    from fastapi.responses import Response
    from ..research.events import listing
    from ..research.materials import frozen
    from ..sessions.native import clean
    from ..runner_config import connections
    db=request.app.state.db;run=service.get_run(db,run_id)
    secret_values=[connections.decrypt(request.app.state.settings,r['id'],r['secret_cipher']) for r in db.execute('SELECT id,secret_cipher FROM runner_connections')]
    summary={k:run.get(k) for k in ('id','status','skill','skill_version','error','created_at','finished_at','diagnostics')}
    # Exclude prompt/answer and event text by default; retain state/tool/config evidence.
    def scrub(value):
        if isinstance(value,str):return clean(value,secret_values)
        if isinstance(value,list):return [scrub(x) for x in value]
        if isinstance(value,dict):return {k:scrub(v) for k,v in value.items() if k not in ('role_prompt','storage_key')}
        return value
    events=db.execute("SELECT id,kind,created_at,payload_json FROM run_events WHERE run_id=? AND kind NOT IN ('text_delta','text_reset') ORDER BY id LIMIT 1001",(run_id,)).fetchall()
    payload=scrub({'version':1,'events_truncated':len(events)>1000,'run':summary,'materials':frozen(db,run_id),'events':[{'seq':r['id'],'kind':r['kind'],'created_at':r['created_at'],'payload':json.loads(r['payload_json'])} for r in events[:1000]],'excluded':['prompt','answer','terminal_bytes','credentials','headers','role_prompt']})
    return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="firework-debug-{run_id}.json"'})
