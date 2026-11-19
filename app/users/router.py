"""HTTP routes for the local user profile."""
from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse

from ..core.errors import ServiceError
from . import service
from .schemas import PreferenceUpdate, ProfileUpdate

router = APIRouter(prefix='/api/me', tags=['user'])


@router.get('')
async def get_profile(request: Request):
    return account_profile(service.profile_view(request.app.state.db),request)


def account_profile(result,request):
    user=getattr(request.state,"auth_user",None)
    if user:
        result.update(auth_mode="account",account_id=user["id"],username=user["username"],role=user["role"])
        result["capabilities"]["auth"]=True
    return result


@router.patch('')
async def patch_profile(body: ProfileUpdate, request: Request):
    try:
        return account_profile(service.update_profile(request.app.state.db, body),request)
    except ValueError as exc:
        raise ServiceError(422, str(exc)) from exc


@router.post('/avatar')
async def upload_avatar(request: Request, avatar: UploadFile = File(...)):
    data = await avatar.read(3 * 1024 * 1024)
    try:
        return account_profile(service.save_avatar(request.app.state.db, request.app.state.settings, data, avatar.filename or ''),request)
    except ValueError as exc:
        raise ServiceError(422, str(exc)) from exc


@router.get('/avatar/{storage_key}')
async def get_avatar(storage_key: str, request: Request):
    path = service.avatar_path(request.app.state.settings, storage_key)
    if not path.is_file() or path.parent.name != 'avatars':
        raise ServiceError(404, 'Avatar not found')
    return FileResponse(path)


@router.get('/preferences')
async def get_preferences(request: Request):
    return service.preferences_view(request.app.state.db)


@router.patch('/preferences')
async def patch_preferences(body: PreferenceUpdate, request: Request):
    try:
        return service.update_preferences(request.app.state.db, body)
    except ValueError as exc:
        raise ServiceError(409, str(exc)) from exc
