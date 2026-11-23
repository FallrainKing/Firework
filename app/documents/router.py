"""Account-scoped document versions, annotations and downloads."""
import asyncio
from typing import Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from urllib.parse import quote

from ..core.errors import ServiceError
from . import service as s
from .export import annotated_pdf, markdown

router = APIRouter(prefix='/api/library/papers', tags=['documents'])


@router.get('/{paper_id}/documents')
async def documents(paper_id: int, request: Request):
    state = request.app.state
    return s.list_documents(state.db, state.settings, paper_id)


@router.post('/{paper_id}/document-versions', status_code=201)
async def upload(paper_id: int, request: Request, file: UploadFile = File(...),
                 label: str = Form(..., min_length=1, max_length=100),
                 document_id: str | None = Form(None), role: Literal['main','supplement'] = Form('main'),
                 title: str = Form('正文', min_length=1,max_length=120),
                 source: str = Form('',max_length=500), description: str = Form('',max_length=2000)):
    state = request.app.state
    s.reader.paper(state.db,paper_id)
    data = await file.read(s.MAX_BYTES + 1)
    if not label.strip() or not title.strip():
        raise ServiceError(400,'版本名称与文档名称不能为空')
    try:
        return s.add_version(state.db,state.settings,paper_id,data,label=label.strip(),filename=file.filename or 'paper.pdf',document_id=document_id,role=role,title=title.strip(),source=source,description=description)
    except BaseException:
        state.db.rollback()
        raise


class DefaultVersion(BaseModel):
    expected_version_id: str | None = Field(...)
    confirmed: Literal[True]


@router.post('/{paper_id}/document-versions/{version_id}/default')
async def default(paper_id: int, version_id: str, body: DefaultVersion, request: Request):
    return await s.make_default(request.app.state.db,request.app.state,paper_id,version_id,body.expected_version_id)


@router.get('/{paper_id}/document-versions/{version_id}/annotations')
async def annotations(paper_id: int, version_id: str, request: Request,
                      origin: Literal['all','personal','ai'] = 'all'):
    db = request.app.state.db
    row = s.version(db,paper_id,version_id)
    return {'annotations': s.annotations(db,paper_id,row,origin),'file_version':row['file_hash']}


@router.get('/{paper_id}/document-versions/{version_id}/file')
async def download(paper_id: int, version_id: str, request: Request,
                   mode: Literal['original','annotated','markdown'] = 'original',
                   origin: Literal['all','personal','ai'] = 'all', inline: bool = False):
    state = request.app.state
    row = s.version(state.db,paper_id,version_id)
    path = s.asset_path(state.settings,row['storage_key'])
    title = s.reader.paper(state.db,paper_id)['title'] or f'paper-{paper_id}'
    stem = ''.join(c for c in f"{title}-{row['label']}" if c not in '\\/:*?"<>|\r\n')[:100] or 'paper'
    suffix = '.md' if mode=='markdown' else ('-annotated.pdf' if mode=='annotated' else '.pdf')
    headers = {'Cache-Control':'private, no-store','Content-Disposition':f"{'inline' if inline and mode=='original' else 'attachment'}; filename*=UTF-8''{quote(stem+suffix,safe='')}"}
    if mode=='original':
        return FileResponse(path,media_type='application/pdf',headers=headers)
    items = s.annotations(state.db,paper_id,row,origin)
    if mode=='markdown':
        return Response(markdown(title,row,items),media_type='text/markdown; charset=utf-8',headers=headers)
    # Freeze the selected annotation snapshot before leaving the request thread.
    if not hasattr(state, 'document_export_limit'):
        state.document_export_limit = asyncio.Semaphore(2)
    async with state.document_export_limit:
        data = await asyncio.to_thread(annotated_pdf,path,items)
    return Response(data,media_type='application/pdf',headers=headers)


from . import migration

@router.post('/{paper_id}/annotation-migration-preview')
async def migration_preview(paper_id:int,body:migration.Preview,request:Request):
    return migration.preview(request.app.state.db,request.app.state.settings,paper_id,body)

@router.post('/{paper_id}/annotation-migrations')
async def migrate_annotations(paper_id:int,body:migration.Confirm,request:Request):
    return migration.apply(request.app.state.db,request.app.state.settings,paper_id,body)

@router.get('/{paper_id}/document-versions/{version_id}/index')
async def version_index(paper_id:int,version_id:str,request:Request,offset:int=0,limit:int=30):
    from ..core.errors import ServiceError
    if offset<0 or not 1<=limit<=100:raise ServiceError(422,'分页范围无效')
    db=request.app.state.db;s.version(db,paper_id,version_id)
    rows=db.execute('SELECT * FROM document_text_chunks WHERE version_id=? ORDER BY chunk_index LIMIT ? OFFSET ?',(version_id,limit+1,offset)).fetchall()
    return {'version_id':version_id,'chunks':[dict(r) for r in rows[:limit]],'has_more':len(rows)>limit,'next_offset':offset+min(limit,len(rows))}
