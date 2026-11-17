"""HTTP routes for research schedules (paths stay under /api/workbench)."""
from fastapi import APIRouter, Request

from . import service
from .schemas import Enable, Schedule

router = APIRouter(prefix='/api/workbench', tags=['workbench'])


@router.get('/schedules')
async def schedules(request: Request):
    return service.schedules_view(request.app.state.db)


@router.post('/schedules', status_code=201)
async def create_schedule(body: Schedule, request: Request):
    return service.create_schedule(request.app.state.db, body)


@router.patch('/schedules/{ident}')
async def enable_schedule(ident: int, body: Enable, request: Request):
    return service.enable_schedule(request.app.state.db, ident, body)


@router.post('/schedules/{ident}/run', status_code=202)
async def run_schedule(ident: int, request: Request):
    return await service.fire_schedule(ident, request.app.state.db, request.app.state)
