"""HTTP routes for the paper library (cards, collections, thumbnails)."""
import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from . import assets, service
from .schemas import CollectionCreate, PaperPatch

router = APIRouter(prefix='/api/library', tags=['library'])


@router.get('/collections')
async def collections(request: Request):
    return service.collections_view(request.app.state.db)


@router.post('/collections', status_code=201)
async def create_collection(body: CollectionCreate, request: Request):
    return service.create_collection(request.app.state.db, body)


@router.get('/papers')
async def papers(request: Request, q: str = Query('', max_length=200), collection_id: int | None = None, reading_status: str | None = Query(None, pattern='^(unread|reading|read)$'), limit: int = Query(60, ge=1, le=100), offset: int = Query(0, ge=0), trashed: bool = False):
    return service.papers_view(request.app.state.db, q, collection_id, reading_status, limit, offset, trashed)


@router.delete('/papers/{paper_id}')
async def trash_paper(paper_id: int, request: Request):
    return service.set_trashed(request.app.state.db, paper_id, True)


@router.post('/papers/{paper_id}/restore')
async def restore_paper(paper_id: int, request: Request):
    return service.set_trashed(request.app.state.db, paper_id, False)


@router.get('/papers/{paper_id}')
async def paper_detail(paper_id: int, request: Request):
    return service.paper_detail(request.app.state.db, paper_id)


@router.get('/papers/{paper_id}/thumbnail')
async def thumbnail(paper_id: int, request: Request):
    row = service.require_paper(request.app.state.db, paper_id)
    try:
        path = await asyncio.to_thread(assets.preview_path, request.app.state.settings, row['pdf_path'])
    except (ValueError, RuntimeError, OSError):
        raise HTTPException(404, 'PDF 预览不可用')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})


@router.post('/papers/{paper_id}/refresh-card')
async def refresh(paper_id: int, request: Request):
    return await service.refresh_card(request.app.state.db, request.app.state.settings, paper_id)


@router.patch('/papers/{paper_id}')
async def edit(paper_id: int, body: PaperPatch, request: Request):
    return service.edit_paper(request.app.state.db, paper_id, body)
