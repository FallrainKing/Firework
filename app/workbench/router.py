"""HTTP routes for workspace state, drafts and image attachments."""
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from . import service
from .schemas import Draft, Workspace

router = APIRouter(prefix='/api/workbench', tags=['workbench'])


@router.get('/recent')
async def recent(request: Request):
    return service.recent(request.app.state.db)


@router.get('/states/{ident}')
async def workspace(ident: str, request: Request):
    return service.get_workspace(request.app.state.db, ident)


@router.put('/states/{ident}')
async def save_workspace(ident: str, body: Workspace, request: Request):
    return service.save_workspace(request.app.state.db, ident, body)


@router.get('/drafts/{sid}/{pid}')
async def draft(sid: int, pid: int, request: Request):
    return service.get_draft(request.app.state.db, sid, pid)


@router.put('/drafts/{sid}/{pid}')
async def save_draft(sid: int, pid: int, body: Draft, request: Request):
    return service.save_draft(request.app.state.db, sid, pid, body)


@router.post('/images', status_code=201)
async def upload_image(request: Request, file: UploadFile = File(...), conversation_id: int = Form(...), paper_id: int = Form(...)):
    data = await file.read(service.MAX_IMAGE + 1)
    return service.upload_image(request.app.state.db, request.app.state.settings, data=data, filename=file.filename or 'image', conversation_id=conversation_id, paper_id=paper_id)


@router.get('/images/{ident}')
async def get_image(ident: str, request: Request):
    path, mime = service.image_file(request.app.state.db, request.app.state.settings, ident)
    return FileResponse(path, media_type=mime, headers={'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff'})
