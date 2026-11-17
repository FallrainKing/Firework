"""Reader management: document, annotations, position and cached Agent translation."""
import asyncio
import hashlib
import json
from typing import Literal
import uuid
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field,model_validator
from ..reader_store import document_info,pdf_file,read_page,validate_context
from .sessions import require_session

router=APIRouter(prefix='/api/reader',tags=['reader'])

def paper(db,ident):
    row=db.execute('SELECT * FROM papers WHERE id=?',(ident,)).fetchone()
    if row is None:raise HTTPException(404,'论文不存在')
    return row

def linked(db,sid,pid):
    require_session(db,sid)
    if not db.execute('SELECT 1 FROM conversation_papers WHERE conversation_id=? AND paper_id=?',(sid,pid)).fetchone():raise HTTPException(400,'当前会话未关联该论文')

def annotation_view(row):
    out=dict(row);out['rects']=json.loads(out.pop('rects_json'));out['points']=json.loads(out.pop('points_json'));return out

class Context(BaseModel):
    paper_id:int
    page:int=Field(ge=1)
    file_version:str=Field(pattern=r'^[a-f0-9]{64}$')
    quote:str=Field('',max_length=4000)
    rects:list[list[float]]=Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def geometry(self):
        for r in self.rects:
            if len(r)!=4 or not all(0<=v<=1 for v in r) or r[0]+r[2]>1.002 or r[1]+r[3]>1.002:raise ValueError('Invalid normalized geometry')
        return self

class Annotation(Context):
    kind:Literal['highlight','note','ink']='highlight'
    content:str=Field('',max_length=8000)
    color:Literal['#f5d76e','#9ed8ff','#a9dfbf','#f4b6d5']='#f5d76e'
    conversation_id:int|None=None
    points:list[list[float]]=Field(default_factory=list,max_length=2000)
    @model_validator(mode='after')
    def ink(self):
        if self.kind=='highlight' and (not self.quote.strip() or not self.rects):raise ValueError('Highlight requires selected text and geometry')
        if self.kind=='note' and not self.content.strip():raise ValueError('Note must not be empty')
        if self.kind=='ink' and len(self.points)<2:raise ValueError('Drawing requires points')
        if any(len(p)!=2 or not all(0<=v<=1 for v in p) for p in self.points):raise ValueError('Invalid drawing geometry')
        return self

class AnnotationPatch(BaseModel):
    content:str|None=Field(None,max_length=8000)
    color:Literal['#f5d76e','#9ed8ff','#a9dfbf','#f4b6d5']|None=None
    deleted:bool|None=None

class Position(BaseModel):
    conversation_id:int
    page:int=Field(ge=1)
    zoom:Literal['fit','1','1.25','1.5','2']='fit'
    tab:Literal['outline','notes','highlights','translations','info']='outline'

class Translation(Context):
    conversation_id:int

@router.get('/papers/{paper_id}')
async def info(paper_id:int,request:Request):
    row=paper(request.app.state.db,paper_id)
    try:return await asyncio.to_thread(document_info,request.app.state.settings,row)
    except (ValueError,RuntimeError,OSError) as e:raise HTTPException(400,str(e))

@router.get('/papers/{paper_id}/file')
async def file(paper_id:int,request:Request):
    try:path,version=pdf_file(request.app.state.settings,paper(request.app.state.db,paper_id))
    except ValueError as e:raise HTTPException(404,str(e))
    return FileResponse(path,media_type='application/pdf',headers={'ETag':'"'+version+'"','Cache-Control':'private, max-age=0, must-revalidate','Content-Disposition':'inline'})

@router.get('/papers/{paper_id}/pages/{page}')
async def page_text(paper_id:int,page:int,request:Request):
    try:return await asyncio.to_thread(read_page,request.app.state.settings,paper(request.app.state.db,paper_id),page)
    except (ValueError,RuntimeError,OSError) as e:raise HTTPException(400,str(e))

@router.get('/papers/{paper_id}/annotations')
async def annotations(paper_id:int,request:Request):
    paper(request.app.state.db,paper_id)
    return {'annotations':[annotation_view(r) for r in request.app.state.db.execute('SELECT * FROM reader_annotations WHERE paper_id=? AND deleted=0 ORDER BY page,created_at',(paper_id,))]}

@router.post('/annotations',status_code=201)
async def annotate(body:Annotation,request:Request):
    db=request.app.state.db
    try:ctx=validate_context(request.app.state.settings,db,body.model_dump(include={'paper_id','page','file_version','quote','rects'}),body.conversation_id)
    except ValueError as e:raise HTTPException(409,str(e))
    ident=uuid.uuid4().hex
    db.execute('INSERT INTO reader_annotations(id,paper_id,conversation_id,file_version,page,kind,quote,content,color,rects_json,points_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,body.paper_id,body.conversation_id,body.file_version,body.page,body.kind,body.quote,body.content,body.color,json.dumps(body.rects),json.dumps(body.points)));db.commit()
    return {**annotation_view(db.execute('SELECT * FROM reader_annotations WHERE id=?',(ident,)).fetchone()),'validation':ctx['validation']}

@router.patch('/annotations/{ident}')
async def edit_annotation(ident:str,body:AnnotationPatch,request:Request):
    db=request.app.state.db;row=db.execute('SELECT * FROM reader_annotations WHERE id=?',(ident,)).fetchone()
    if row is None:raise HTTPException(404,'批注不存在')
    if row['kind']=='note' and body.content is not None and not body.content.strip():raise HTTPException(400,'批注不能为空')
    for key,value in body.model_dump(exclude_unset=True).items():
        if value is not None:db.execute(f'UPDATE reader_annotations SET {key}=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(value,ident))
    db.commit();return annotation_view(db.execute('SELECT * FROM reader_annotations WHERE id=?',(ident,)).fetchone())

@router.get('/papers/{paper_id}/state')
async def state(paper_id:int,conversation_id:int,request:Request):
    db=request.app.state.db;linked(db,conversation_id,paper_id)
    row=db.execute('SELECT * FROM reader_states WHERE conversation_id=? AND paper_id=?',(conversation_id,paper_id)).fetchone()
    return dict(row) if row else {'page':1,'zoom':'fit','tab':'outline'}

@router.put('/papers/{paper_id}/state')
async def save_state(paper_id:int,body:Position,request:Request):
    db=request.app.state.db;linked(db,body.conversation_id,paper_id)
    try:doc=await asyncio.to_thread(document_info,request.app.state.settings,paper(db,paper_id))
    except ValueError as e:raise HTTPException(400,str(e))
    if body.page>doc['page_count']:raise HTTPException(400,'页码超出范围')
    db.execute('INSERT INTO reader_states(conversation_id,paper_id,page,zoom,tab) VALUES (?,?,?,?,?) ON CONFLICT(conversation_id,paper_id) DO UPDATE SET page=excluded.page,zoom=excluded.zoom,tab=excluded.tab,updated_at=CURRENT_TIMESTAMP',(body.conversation_id,paper_id,body.page,body.zoom,body.tab));db.commit()
    return body.model_dump()

@router.get('/papers/{paper_id}/translations')
async def translations(paper_id:int,request:Request):
    paper(request.app.state.db,paper_id)
    rows=request.app.state.db.execute('SELECT t.*,r.status,r.answer,r.error FROM reader_translations t JOIN agent_runs r ON r.id=t.run_id WHERE t.paper_id=? AND t.deleted=0 ORDER BY t.created_at DESC',(paper_id,)).fetchall()
    return {'translations':[dict(r) for r in rows]}

@router.post('/translations')
async def translate(body:Translation,request:Request):
    from .agent import RunCreate,create_run
    db=request.app.state.db;linked(db,body.conversation_id,body.paper_id)
    if not body.quote.strip():raise HTTPException(400,'请先选择需要翻译的原文')
    try:context=validate_context(request.app.state.settings,db,body.model_dump(exclude={'conversation_id'}),body.conversation_id)
    except ValueError as e:raise HTTPException(409,str(e))
    digest=str(body.page)+':'+hashlib.sha256(body.quote.strip().encode()).hexdigest()
    old=db.execute('SELECT t.*,r.status,r.answer FROM reader_translations t JOIN agent_runs r ON r.id=t.run_id WHERE t.paper_id=? AND t.file_version=? AND t.quote_hash=? AND t.language=?',(body.paper_id,body.file_version,digest,'zh-CN')).fetchone()
    if old and old['status']!='failed':
        db.execute('UPDATE reader_translations SET deleted=0 WHERE id=?',(old['id'],));db.commit()
        return {**dict(old),'deleted':0,'cached':True}
    run=await create_run(RunCreate(conversation_id=body.conversation_id,prompt='请把本次选中的原文准确翻译成简体中文，只输出译文，保留专业术语、数字与公式。',contexts=[context],purpose='translate'),request)
    ident=old['id'] if old else uuid.uuid4().hex
    db.execute("INSERT INTO reader_translations(id,paper_id,conversation_id,page,file_version,quote,quote_hash,run_id) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(paper_id,file_version,quote_hash,language) DO UPDATE SET run_id=excluded.run_id,conversation_id=excluded.conversation_id,deleted=0",(ident,body.paper_id,body.conversation_id,body.page,body.file_version,body.quote,digest,run['id']));db.commit()
    return {'id':ident,'run_id':run['id'],'status':run['status'],'cached':False}

class TranslationVisibility(BaseModel):
    deleted:bool

@router.patch('/translations/{ident}')
async def translation_visibility(ident:str,body:TranslationVisibility,request:Request):
    db=request.app.state.db
    if not db.execute('SELECT 1 FROM reader_translations WHERE id=?',(ident,)).fetchone():raise HTTPException(404,'翻译记录不存在')
    db.execute('UPDATE reader_translations SET deleted=? WHERE id=?',(body.deleted,ident));db.commit()
    return {'id':ident,'deleted':body.deleted}
