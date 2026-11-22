"""Bounded REST gateway; no arbitrary paths, model runs, credentials or execution access."""
import hashlib
import json
from fastapi import APIRouter,Request,Header
from pydantic import BaseModel,Field,ConfigDict
from fastapi.responses import FileResponse
from . import auth
from ..core.errors import ServiceError
from ..papers import service as papers
from ..papers.schemas import PaperPatch
from ..reader import service as reader,repository as reader_repo,pages
from ..reader.schemas import Annotation,AnnotationPatch
from ..documents import service as documents
management=APIRouter(prefix='/api/me/access-tokens',tags=['external authorization'])
router=APIRouter(prefix='/api/external/v1',tags=['external papers'])

@management.get('')
def tokens(request:Request):return auth.listing(request.app.state.auth_store,request.state.auth_user)
@management.post('',status_code=201)
def create_token(body:auth.TokenCreate,request:Request):return auth.create(request.app.state.auth_store,request.state.auth_user,request.app.state.db,body)
@management.delete('/{ident}')
def revoke_token(ident:str,request:Request):return auth.revoke(request.app.state.auth_store,request.state.auth_user,ident)

class ExternalPaperPatch(PaperPatch):
    model_config=ConfigDict(extra='forbid')

class PaperCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=500)
    authors:list[str]=Field(default_factory=list,max_length=100)
    abstract:str=Field('',max_length=12000)
class ExternalNote(Annotation):
    model_config=ConfigDict(extra='forbid')
    conversation_id:None=None
class ExternalPatch(AnnotationPatch):
    model_config=ConfigDict(extra='forbid')
    expected_etag:str=Field(pattern=r'^[a-f0-9]{64}$')

def etag(row):return hashlib.sha256(json.dumps(dict(row),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def annotation(row):return reader.annotation_view(row)|{'etag':etag(row)}
class Transaction:
    """Domain helpers may commit; the external operation owns the outer transaction."""
    def __init__(self,db):self.db=db
    def __getattr__(self,key):return getattr(self.db,key)
    def commit(self):pass
    def __enter__(self):return self
    def __exit__(self,*args):return False

def mutate(request,body,key,operation):
    from ..core.db import get_conn
    token=request.state.external_token
    db=get_conn(request.app.state.settings)
    if not key or len(key)>80:raise ServiceError(422,'写入需要 1–80 字符 Idempotency-Key')
    digest=hashlib.sha256((request.method+request.url.path+body.model_dump_json()).encode()).hexdigest()
    try:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT * FROM external_operations WHERE token_id=? AND request_key=?',(token['id'],key)).fetchone()
        if prior:
            if prior['body_hash']!=digest:raise ServiceError(409,'幂等键已用于其他请求')
            db.commit();return json.loads(prior['result_json'])
        result=operation(Transaction(db))
        db.execute('INSERT INTO external_operations(token_id,request_key,body_hash,result_json) VALUES (?,?,?,?)',(token['id'],key,digest,json.dumps(result,ensure_ascii=False)))
        db.execute('INSERT INTO external_audit(token_id,action,target) VALUES (?,?,?)',(token['id'],request.method,request.url.path))
        db.commit();return result
    except Exception:db.rollback();raise
    finally:db.close()

@router.get('/capabilities')
def capabilities(request:Request):
    t=request.state.external_token
    return {'version':'v1','scopes':json.loads(t['scopes_json']),'paper_ids':json.loads(t['paper_ids_json']) if t['paper_ids_json'] else None,'model_operations':False,'writes_require_idempotency':True,'pdf_upload':False,'permanent_delete':False}

@router.get('/collections')
def collections(request:Request):
    auth.require(request,'papers:read')
    return papers.collections_view(request.app.state.db)

@router.get('/papers')
def listing(request:Request,q:str='',limit:int=20,offset:int=0):
    token=auth.require(request,'papers:read') if not request.state.external_token['paper_ids_json'] else request.state.external_token
    if 'papers:read' not in json.loads(token['scopes_json']):raise ServiceError(403,'缺少 papers:read')
    if len(q)>200 or not 1<=limit<=100 or offset<0:raise ServiceError(422,'查询范围无效')
    allowed=json.loads(token['paper_ids_json']) if token['paper_ids_json'] else None
    if allowed is None:return papers.papers_view(request.app.state.db,q,limit=limit,offset=offset)
    # Restrict in SQL, before applying pagination or returning metadata.
    db=request.app.state.db;marks=','.join('?' for _ in allowed)
    rows=db.execute(f"SELECT * FROM papers WHERE id IN ({marks}) AND deleted_at IS NULL AND (instr(lower(coalesce(title,'')),lower(?))>0 OR instr(lower(coalesce(abstract,'')),lower(?))>0) ORDER BY id DESC",[*allowed,q,q]).fetchall()
    return {'papers':[papers.card(db,r) for r in rows[offset:offset+limit]],'total':len(rows),'offset':offset,'has_more':offset+limit<len(rows)}

@router.get('/papers/{pid}')
def detail(pid:int,request:Request):
    auth.require(request,'papers:read',pid);return papers.paper_detail(request.app.state.db,pid)
@router.post('/papers',status_code=201)
def create(body:PaperCreate,request:Request,idempotency_key:str|None=Header(None)):
    auth.require(request,'papers:write')
    if not body.title.strip() or any(not a.strip() or len(a)>240 for a in body.authors):raise ServiceError(422,'题名或作者字段无效')
    def op(db):
        pid=db.execute("INSERT INTO papers(title,authors,abstract,source) VALUES (?,?,?,'import')",(body.title.strip(),json.dumps(body.authors,ensure_ascii=False),body.abstract)).lastrowid
        return papers.paper_detail(db,pid)
    return mutate(request,body,idempotency_key,op)
@router.patch('/papers/{pid}')
def edit(pid:int,body:ExternalPaperPatch,request:Request,idempotency_key:str|None=Header(None)):
    auth.require(request,'papers:write',pid)
    return mutate(request,body,idempotency_key,lambda db:papers.edit_paper(db,pid,body))
@router.get('/papers/{pid}/document')
def document(pid:int,request:Request):
    auth.require(request,'papers:read',pid)
    try:return pages.document_info(request.app.state.settings,reader.paper(request.app.state.db,pid)) | {'pdf_url':f'/api/external/v1/papers/{pid}/file'}
    except ValueError as e:raise ServiceError(409,str(e)) from None
@router.get('/papers/{pid}/pages/{page}')
def page(pid:int,page:int,request:Request):
    auth.require(request,'papers:read',pid)
    if page<1:raise ServiceError(422,'页码无效')
    try:return pages.read_page(request.app.state.settings,reader.paper(request.app.state.db,pid),page)
    except ValueError as e:raise ServiceError(409,str(e)) from None
@router.get('/papers/{pid}/file')
def file(pid:int,request:Request):
    auth.require(request,'files:read',pid)
    try:path,_=pages.pdf_file(request.app.state.settings,reader.paper(request.app.state.db,pid))
    except ValueError as e:raise ServiceError(409,str(e)) from None
    return FileResponse(path,media_type='application/pdf',filename=f'paper-{pid}.pdf')
@router.get('/papers/{pid}/annotations')
def notes(pid:int,request:Request):
    auth.require(request,'annotations:read',pid);reader.paper(request.app.state.db,pid)
    return {'annotations':[annotation(r) for r in reader_repo.list_annotations(request.app.state.db,pid)]}
@router.post('/papers/{pid}/annotations',status_code=201)
def add_note(pid:int,body:ExternalNote,request:Request,idempotency_key:str|None=Header(None)):
    auth.require(request,'annotations:write',pid)
    if body.paper_id!=pid:raise ServiceError(422,'正文与路径论文 ID 不一致')
    def op(db):
        result=reader.annotate(db,request.app.state.settings,body)
        return annotation(reader_repo.find_annotation(db,result['id']))
    return mutate(request,body,idempotency_key,op)
@router.patch('/papers/{pid}/annotations/{ident}')
def edit_note(pid:int,ident:str,body:ExternalPatch,request:Request,idempotency_key:str|None=Header(None)):
    auth.require(request,'annotations:write',pid)
    def op(db):
        row=reader_repo.find_annotation(db,ident)
        if row is None or row['paper_id']!=pid:raise ServiceError(404,'批注不存在')
        if etag(row)!=body.expected_etag:raise ServiceError(409,'批注已变化，请刷新后重试')
        reader.edit_annotation(db,ident,AnnotationPatch(**body.model_dump(exclude={'expected_etag'},exclude_unset=True)))
        return annotation(reader_repo.find_annotation(db,ident))
    return mutate(request,body,idempotency_key,op)
