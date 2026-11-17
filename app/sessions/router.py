"""HTTP routes for task sessions, templates and categories."""
from fastapi import APIRouter, Query, Request

from . import service
from .schemas import Name, SessionCreate, SessionPatch, TemplateCreate

router = APIRouter(prefix='/api/sessions', tags=['sessions'])


@router.get('/templates')
async def templates(request: Request):
    return service.templates_view(request.app.state.db)


@router.post('/templates', status_code=201)
async def create_template(body: TemplateCreate, request: Request):
    return service.create_template(request.app.state.db, body)


@router.get('/categories')
async def categories(request: Request):
    return service.categories_view(request.app.state.db)


@router.post('/categories', status_code=201)
async def create_category(body: Name, request: Request):
    return service.create_category(request.app.state.db, body)


@router.get('')
async def list_sessions(request: Request, q: str = Query('', max_length=200), kind: str | None = None, paper_id: int | None = None, category_id: int | None = None, archived: bool = False, limit: int = Query(100, ge=1, le=200)):
    return service.list_sessions(request.app.state.db, q=q, kind=kind, paper_id=paper_id, category_id=category_id, archived=archived, limit=limit)


@router.post('', status_code=201)
async def create_session(body: SessionCreate, request: Request):
    return service.create_session(request.app.state.db, body)


@router.get('/{session_id}')
async def detail(session_id: int, request: Request):
    return service.session_detail(request.app.state.db, session_id)


@router.get('/{session_id}/runs')
async def session_runs(session_id: int, request: Request, before: int | None = None, limit: int = Query(50, ge=1, le=100)):
    return service.session_runs(request.app.state.db, session_id, before, limit)


@router.patch('/{session_id}')
async def update(session_id: int, body: SessionPatch, request: Request):
    return service.update_session(request.app.state.db, session_id, body)
