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
