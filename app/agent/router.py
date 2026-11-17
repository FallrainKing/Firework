"""HTTP routes for agent status and persisted runs."""
from fastapi import APIRouter, Query, Request

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


@router.get('/library')
async def search_library(request: Request, q: str = Query('', max_length=200)):
    return service.search_library(request.app.state.db, q)


@router.post('/runs', status_code=202)
async def create_run(body: RunCreate, request: Request):
    return await service.create_run(body, request.app.state)
