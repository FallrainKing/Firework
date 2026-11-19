"""HTTP routes for dynamic skill management."""
from __future__ import annotations

from fastapi import APIRouter, File, Query, Request, UploadFile

from ..core.errors import ServiceError
from . import service
from .schemas import CategoryCreate, CategoryUpdate, SkillInstall, SkillUpdate

router = APIRouter(prefix='/api/skills', tags=['skills'])


@router.post('/imports')
async def import_skill(request: Request, archive: UploadFile = File(...)):
    settings = request.app.state.settings
    data = await archive.read(21 * 1024 * 1024)
    try:
        return service.import_skill_archive(
            request.app.state.db,
            settings,
            data,
            archive.filename or '',
        )
    except ValueError as exc:
        raise ServiceError(422, str(exc)) from exc


@router.get('/imports/{import_id}')
async def get_import(import_id: str, request: Request):
    try:
        return service.view_import(request.app.state.db, import_id)
    except ValueError as exc:
        raise ServiceError(404, str(exc)) from exc


@router.post('/imports/{import_id}/install')
async def install_skill(import_id: str, body: SkillInstall, request: Request):
    try:
        return service.install_skill(request.app.state.db, request.app.state.settings, import_id, body)
    except ValueError as exc:
        raise ServiceError(409, str(exc)) from exc


@router.get('')
async def list_skills(
    request: Request,
    q: str = Query('', max_length=200),
    status: str | None = Query(None, pattern='^(enabled|disabled|archived)$'),
    category_id: int | None = None,
    source: str | None = Query(None, pattern='^(builtin|zip)$'),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
):
    return service.list_skills_view(
        request.app.state.db,
        q=q,
        status=status,
        category_id=category_id,
        source=source,
        limit=limit,
        offset=offset,
    )


@router.get('/registry')
async def registry(request: Request):
    return service.registry_view(request.app.state.db)


@router.get('/categories')
async def categories(request: Request):
    return {'categories': service.list_categories_view(request.app.state.db)}


@router.post('/categories', status_code=201)
async def create_category(body: CategoryCreate, request: Request):
    try:
        return service.create_category(request.app.state.db, body)
    except ValueError as exc:
        raise ServiceError(409, str(exc)) from exc


@router.patch('/categories/{category_id}')
async def update_category(category_id: int, body: CategoryUpdate, request: Request):
    try:
        return service.update_category(request.app.state.db, category_id, body)
    except ValueError as exc:
        raise ServiceError(404, str(exc)) from exc


@router.delete('/categories/{category_id}', status_code=204)
async def delete_category(category_id: int, request: Request):
    try:
        service.delete_category(request.app.state.db, category_id)
    except ValueError as exc:
        raise ServiceError(404, str(exc)) from exc


@router.get('/{skill_id}')
async def get_skill(skill_id: str, request: Request):
    try:
        return service.skill_detail(request.app.state.db, skill_id)
    except ValueError as exc:
        raise ServiceError(404, str(exc)) from exc


@router.patch('/{skill_id}')
async def patch_skill(skill_id: str, body: SkillUpdate, request: Request):
    try:
        return service.update_skill(request.app.state.db, skill_id, body)
    except ValueError as exc:
        raise ServiceError(404, str(exc)) from exc


@router.post('/{skill_id}/enable')
async def enable_skill(skill_id: str, request: Request):
    try:
        return service.enable_skill(request.app.state.db, skill_id)
    except ValueError as exc:
        raise ServiceError(409, str(exc)) from exc


@router.post('/{skill_id}/disable')
async def disable_skill(skill_id: str, request: Request):
    try:
        return service.disable_skill(request.app.state.db, skill_id)
    except ValueError as exc:
        raise ServiceError(409, str(exc)) from exc
