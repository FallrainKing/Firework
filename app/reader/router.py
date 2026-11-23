"""HTTP routes for the reader: document, annotations, position, translations."""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from . import pages, service
from .schemas import Annotation, AnnotationPatch, Position, Translation, TranslationVisibility

router = APIRouter(prefix='/api/reader', tags=['reader'])


@router.get('/papers/{paper_id}')
async def info(paper_id: int, request: Request, version_id:str|None=None):
    row = service.paper(request.app.state.db, paper_id)
    if version_id:
        from ..documents import service as documents
        v=documents.version(request.app.state.db,paper_id,version_id)
        row=dict(row)|{'pdf_path':str(documents.asset_path(request.app.state.settings,v['storage_key']))}
        data=await asyncio.to_thread(pages.document_info,request.app.state.settings,row)
        data.update(document_version_id=version_id,pdf_url=f'/api/library/papers/{paper_id}/document-versions/{version_id}/file?inline=true')
        return data
    try:
        data=await asyncio.to_thread(pages.document_info, request.app.state.settings, row)
        data['document_version_id']=row['default_version_id']
        return data
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
async def state(paper_id: int, conversation_id: int, request: Request, file_version:str|None=None):
    return service.get_state(request.app.state.db, conversation_id, paper_id,file_version)


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


from .schemas import Context
@router.post('/anchors/locate')
async def locate_anchor(body:Context,request:Request):
    from .anchors import locate
    return locate(request.app.state.db,request.app.state.settings,body)


@router.post('/annotations/{ident}/adopt',status_code=201)
def adopt_external_annotation(ident:str,request:Request):
    import json
    db=request.app.state.db;row=db.execute("SELECT * FROM reader_annotations WHERE id=? AND origin='ai' AND source_artifact_id IS NOT NULL",(ident,)).fetchone()
    from ..core.errors import ServiceError
    if not row:raise ServiceError(404,'外部AI批注不存在')
    old=db.execute('SELECT id FROM reader_annotations WHERE source_annotation_id=? AND origin=?',(ident,'ai_adopted')).fetchone()
    if old:return service.annotation_view(db.execute('SELECT * FROM reader_annotations WHERE id=?',(old['id'],)).fetchone())
    body=Annotation(paper_id=row['paper_id'],file_version=row['file_version'],page=row['page'],kind=row['kind'],content=row['content'],quote=row['quote'],rects=json.loads(row['rects_json']),points=json.loads(row['points_json']),color=row['color'])
    with db:
        aid=service.insert_annotation_record(db,body)
        db.execute("UPDATE reader_annotations SET origin='ai_adopted',source_annotation_id=?,document_version_id=?,source_artifact_id=? WHERE id=?",(ident,row['document_version_id'],row['source_artifact_id'],aid))
    return service.annotation_view(db.execute('SELECT * FROM reader_annotations WHERE id=?',(aid,)).fetchone())
