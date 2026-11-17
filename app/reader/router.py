"""HTTP routes for the reader: document, annotations, position, translations."""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import pages, service
from .schemas import Annotation, AnnotationPatch, Position, Translation, TranslationVisibility

router = APIRouter(prefix='/api/reader', tags=['reader'])


@router.get('/papers/{paper_id}')
async def info(paper_id: int, request: Request):
    row = service.paper(request.app.state.db, paper_id)
    try:
        return await asyncio.to_thread(pages.document_info, request.app.state.settings, row)
    except (ValueError, RuntimeError, OSError) as e:
        raise HTTPException(400, str(e))


@router.get('/papers/{paper_id}/file')
async def file(paper_id: int, request: Request):
    try:
        path, version = pages.pdf_file(request.app.state.settings, service.paper(request.app.state.db, paper_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, media_type='application/pdf', headers={'ETag': '"' + version + '"', 'Cache-Control': 'private, max-age=0, must-revalidate', 'Content-Disposition': 'inline'})


@router.get('/papers/{paper_id}/pages/{page}')
async def page_text(paper_id: int, page: int, request: Request):
    try:
        return await asyncio.to_thread(pages.read_page, request.app.state.settings, service.paper(request.app.state.db, paper_id), page)
    except (ValueError, RuntimeError, OSError) as e:
        raise HTTPException(400, str(e))


@router.get('/papers/{paper_id}/annotations')
async def annotations(paper_id: int, request: Request):
    return service.annotations(request.app.state.db, paper_id)


@router.post('/annotations', status_code=201)
async def annotate(body: Annotation, request: Request):
    return service.annotate(request.app.state.db, request.app.state.settings, body)


@router.patch('/annotations/{ident}')
async def edit_annotation(ident: str, body: AnnotationPatch, request: Request):
    return service.edit_annotation(request.app.state.db, ident, body)


@router.get('/papers/{paper_id}/state')
async def state(paper_id: int, conversation_id: int, request: Request):
    return service.get_state(request.app.state.db, conversation_id, paper_id)


@router.put('/papers/{paper_id}/state')
async def save_state(paper_id: int, body: Position, request: Request):
    return await service.save_state(request.app.state.db, request.app.state.settings, paper_id, body)


@router.get('/papers/{paper_id}/translations')
async def translations(paper_id: int, request: Request):
    return service.translations(request.app.state.db, paper_id)


@router.post('/translations')
async def translate(body: Translation, request: Request):
    return await service.translate(request.app.state.db, request.app.state.settings, body, request.app.state)


@router.patch('/translations/{ident}')
async def translation_visibility(ident: str, body: TranslationVisibility, request: Request):
    return service.set_translation_visibility(request.app.state.db, ident, body)
