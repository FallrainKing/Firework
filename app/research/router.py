from fastapi import APIRouter,Request,Query
from fastapi.responses import Response
from . import service as s
from .schemas import ArtifactWrite,KnowledgeWrite,Transition
router=APIRouter(prefix='/api/research',tags=['research assets'])

@router.get('/artifacts')
async def artifacts(request:Request,q:str=Query('',max_length=200),paper_id:int|None=None,before:int|None=None,limit:int=Query(30,ge=1,le=100)):
    return s.artifact_list(request.app.state.db,q,paper_id,before,limit)

@router.post('/artifacts',status_code=201)
async def create_artifact(body:ArtifactWrite,request:Request):
    db=request.app.state.db
    with db:return s.artifact_save(db,request.app.state.settings,body)

@router.get('/artifacts/{ident}')
async def artifact(ident:str,request:Request,revision:int|None=Query(None,ge=1)):
    return s.artifact_view(request.app.state.db,ident,revision)

@router.patch('/artifacts/{ident}')
async def revise_artifact(ident:str,body:ArtifactWrite,request:Request):
    db=request.app.state.db
    with db:return s.artifact_save(db,request.app.state.settings,body,ident)

@router.get('/artifacts/{ident}/markdown')
async def artifact_markdown(ident:str,request:Request,revision:int|None=Query(None,ge=1)):
    item=s.artifact_view(request.app.state.db,ident,revision)
    return Response(item['markdown'],media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="artifact-{ident}-v{item["revision"]}.md"'})

@router.get('/knowledge/recall')
async def recall(request:Request,q:str=Query('',max_length=200),limit:int=Query(20,ge=1,le=50)):
    return s.knowledge_list(request.app.state.db,q,limit=limit,recall=True)

@router.get('/knowledge')
async def knowledge(request:Request,q:str=Query('',max_length=200),state:str|None=Query(None,pattern='^(candidate|published|rejected|revoked)$'),before:int|None=None,limit:int=Query(30,ge=1,le=100)):
    return s.knowledge_list(request.app.state.db,q,state,before,limit)

@router.post('/knowledge',status_code=201)
async def candidate(body:KnowledgeWrite,request:Request):
    db=request.app.state.db
    with db:return s.knowledge_save(db,body)

@router.get('/knowledge/{ident}')
async def knowledge_detail(ident:str,request:Request,revision:int|None=Query(None,ge=1)):
    return s.knowledge_view(request.app.state.db,ident,revision)

@router.patch('/knowledge/{ident}')
async def knowledge_revise(ident:str,body:KnowledgeWrite,request:Request):
    db=request.app.state.db
    with db:return s.knowledge_save(db,body,ident)

@router.post('/knowledge/{ident}/transition')
async def knowledge_transition(ident:str,body:Transition,request:Request):
    db=request.app.state.db
    with db:return s.transition(db,ident,body)

@router.get('/audit/{kind}/{ident}')
async def audit(kind:str,ident:str,request:Request):
    from ..core.errors import ServiceError
    if kind not in ('artifact','knowledge'):raise ServiceError(404,'记录不存在')
    s.require(request.app.state.db,'research_artifacts' if kind=='artifact' else 'knowledge_items',ident)
    return {'audit':[dict(r) for r in request.app.state.db.execute('SELECT * FROM research_audit WHERE resource_type=? AND resource_id=? ORDER BY id DESC LIMIT 100',(kind,ident))]}


from pydantic import BaseModel,Field
class ImportExisting(BaseModel):
    limit:int=Field(30,ge=1,le=100)

@router.post('/import-existing')
async def import_existing(body:ImportExisting,request:Request):
    db=request.app.state.db
    with db:return s.import_existing(db,request.app.state.settings,body.limit)


from fastapi import UploadFile,File,Form
from fastapi.responses import FileResponse
from . import files

@router.post('/files',status_code=201)
async def upload_research_file(request:Request,paper_id:int=Form(...),file:UploadFile=File(...)):
    data=await file.read(files.MAX_SIZE+1);db=request.app.state.db
    with db:return files.store(db,request.app.state.settings,paper_id,file.filename or 'file',data)

@router.get('/files/{ident}')
async def research_file(ident:str,request:Request):
    r,path=files.resolve(request.app.state.db,request.app.state.settings,ident)
    return FileResponse(path,media_type='application/octet-stream',filename=r['filename'],headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})
