"""HTTP routes for task sessions, templates and categories."""
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel,Field

from . import service
from . import terminal as terminal_service
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


@router.get('/{session_id}/native')
async def native_session(session_id:int,request:Request,offset:int=Query(0,ge=0),source:str|None=Query(None,pattern='^[a-f0-9]{32}$'),limit:int=Query(50,ge=1,le=100)):
    from . import native
    return await native.view(request.app.state,session_id,offset,source,limit)


@router.get('/{session_id}/terminal-capabilities')
async def terminal_capabilities(session_id:int,request:Request):
    service.require_session(request.app.state.db,session_id)
    from .terminal import call
    return await call('GET','/terminal-capabilities')

@router.post('/{session_id}/terminal')
async def start_terminal(session_id:int,body:terminal_service.Start,request:Request):
    from .terminal import start
    return await start(request.app.state,session_id,body)

@router.get('/{session_id}/terminal')
async def read_terminal(session_id:int,request:Request,offset:int=Query(0,ge=0),generation:str|None=Query(None,pattern='^[a-f0-9]{32}$'),controller_id:str|None=Query(None,pattern='^[a-f0-9]{32}$')):
    from .terminal import call,require_terminal
    require_terminal(request.app.state.db,session_id)
    return await call('GET',f'/terminals/{session_id}',params={'offset':offset,**({'generation':generation} if generation else {}),**({'controller_id':controller_id} if controller_id else {})})

@router.post('/{session_id}/terminal/input')
async def input_terminal(session_id:int,body:terminal_service.Input,request:Request):
    from .terminal import call,require_terminal
    require_terminal(request.app.state.db,session_id)
    return await call('POST',f'/terminals/{session_id}/input',json=body.model_dump())

@router.post('/{session_id}/terminal/resize')
async def resize_terminal(session_id:int,body:terminal_service.Resize,request:Request):
    from .terminal import call,require_terminal
    require_terminal(request.app.state.db,session_id)
    return await call('POST',f'/terminals/{session_id}/resize',json=body.model_dump())

@router.post('/{session_id}/terminal/stop')
async def stop_terminal(session_id:int,body:terminal_service.Control,request:Request):
    from .terminal import call,require_terminal
    require_terminal(request.app.state.db,session_id)
    return await call('POST',f'/terminals/{session_id}/stop',json=body.model_dump())


from . import forks

@router.post('/{session_id}/fork-preview')
async def fork_preview(session_id:int,body:forks.Preview,request:Request):
    return forks.preview(request.app.state,session_id,body)

@router.post('/{session_id}/forks',status_code=201)
async def fork_session(session_id:int,body:forks.Confirm,request:Request):
    return forks.create(request.app.state,session_id,body)


@router.get('/{session_id}/terminal/files')
async def terminal_files(session_id:int,request:Request):
    from .workspace_files import listing
    return listing(request.app.state,session_id)

@router.get('/{session_id}/terminal/file')
async def terminal_file(session_id:int,request:Request,path:str=Query(...,min_length=1,max_length=500),sha256:str=Query(...,pattern='^[a-f0-9]{64}$')):
    from .workspace_files import read
    from fastapi.responses import Response
    from urllib.parse import quote
    data,_=read(request.app.state,session_id,path,sha256)
    return Response(data,media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(path.split('/')[-1],safe=''),'Content-Security-Policy':"default-src 'none'; sandbox"})

class SaveTerminalFile(BaseModel):
    path:str=Field(min_length=1,max_length=500)
    sha256:str=Field(pattern='^[a-f0-9]{64}$')
    paper_id:int=Field(ge=1)

@router.post('/{session_id}/terminal/artifacts',status_code=201)
async def save_terminal_file(session_id:int,body:SaveTerminalFile,request:Request):
    from .workspace_files import read
    from . import repository
    from ..research import files,service as research
    from ..research.schemas import ArtifactWrite
    db=request.app.state.db
    if body.paper_id not in repository.paper_ids(db,session_id):
        from ..core.errors import ServiceError
        raise ServiceError(404,'论文未关联此会话')
    data,digest=read(request.app.state,session_id,body.path,body.sha256)
    source=f'terminal:{session_id}:{digest}'
    existing=db.execute('SELECT id FROM research_artifacts WHERE source_key=?',(source,)).fetchone()
    if existing:return research.artifact_view(db,existing[0])
    with db:
        file=files.store(db,request.app.state.settings,body.paper_id,body.path.split('/')[-1],data)
        return research.artifact_save(db,request.app.state.settings,ArtifactWrite(title=file['filename'],kind='file',markdown='来自隔离终端的工作文件，尚未经研究审核。',paper_ids=[body.paper_id],file_ids=[file['hash']],status='partial',producer=f'terminal-session:{session_id}'),origin='terminal',source_key=source)
