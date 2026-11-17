"""HTTP routes for import submissions and the private internal execute hook."""
from fastapi import APIRouter, File, Form, Request, UploadFile

from ..core.db import get_conn
from . import service
from .schemas import Source

router = APIRouter(prefix='/api/imports', tags=['imports'])
internal = APIRouter(prefix='/api/internal', tags=['internal'])


@router.post('/source', status_code=202)
async def source(body: Source, request: Request):
    return await service.submit_source(request.app.state.db, body, request.app.state)


@router.post('/upload', status_code=202)
async def upload(request: Request, file: UploadFile = File(...), request_key: str = Form(...), collection_id: int | None = Form(None), target_paper_id: int | None = Form(None)):
    data = await file.read(service.MAX_PDF_BYTES + 1)
    return await service.upload_import(request.app.state.db, request.app.state.settings, request.app.state, data=data, filename=file.filename or 'upload.pdf', request_key=request_key, collection_id=collection_id, target_paper_id=target_paper_id)


@router.get('')
async def list_imports(request: Request):
    return service.imports_view(request.app.state.db)


@router.get('/{ident}')
async def get_import(ident: str, request: Request):
    return service.get_import(request.app.state.db, ident)


@router.post('/{ident}/retry')
async def retry(ident: str, request: Request):
    return await service.retry_import(request.app.state.db, ident, request.app.state)


@internal.post('/imports/{ident}/execute')
async def execute(ident: str, request: Request):
    db = get_conn(request.app.state.settings)
    try:
        return await service.execute_import(
            db, request.app.state.settings, request.app.state,
            ident=ident, run_id=request.headers.get('x-research-run-id'), token=request.headers.get('x-research-tool-token', ''),
        )
    finally:
        db.close()
