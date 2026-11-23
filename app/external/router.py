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
    if not key or len(key)>80:raise ServiceError(422,'写入需要 1–80 字符 Idempotency-Key')
    db=get_conn(request.app.state.settings)
    digest=hashlib.sha256((request.method+request.url.path+body.model_dump_json()).encode()).hexdigest()
    try:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute('SELECT * FROM external_operations WHERE token_id=? AND request_key=?',(token['id'],key)).fetchone()
        if prior:
            if prior['body_hash']!=digest:raise ServiceError(409,'幂等键已用于其他请求',code='idempotency_conflict')
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
    return {'version':'v1','scopes':json.loads(t['scopes_json']),'paper_ids':json.loads(t['paper_ids_json']) if t['paper_ids_json'] else None,'model_operations':False,'writes_require_idempotency':True,'pdf_upload':False,'permanent_delete':False,'annotation_recovery':True,'external_frontier_reports':True,'research_artifacts':True,'knowledge_candidates':True,'published_knowledge_recall':True,'run_timeline':True,'research_asset_upload':True}

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
    def op(db):
        try:return papers.edit_paper(db,pid,body)
        except ServiceError as e:
            if e.status==409:e.code='metadata_conflict'
            raise
    return mutate(request,body,idempotency_key,op)
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
def notes(pid:int,request:Request,include_deleted:bool=False):
    auth.require(request,'annotations:read',pid);reader.paper(request.app.state.db,pid)
    rows=request.app.state.db.execute('SELECT * FROM reader_annotations WHERE paper_id=? ORDER BY page,created_at',(pid,)).fetchall() if include_deleted else reader_repo.list_annotations(request.app.state.db,pid)
    return {'annotations':[annotation(r) for r in rows]}
@router.post('/papers/{pid}/annotations',status_code=201)
def add_note(pid:int,body:ExternalNote,request:Request,idempotency_key:str|None=Header(None)):
    auth.require(request,'annotations:write',pid)
    if body.paper_id!=pid:raise ServiceError(422,'正文与路径论文 ID 不一致')
    def op(db):
        try:result=reader.annotate(db,request.app.state.settings,body)
        except ServiceError as e:
            if e.status==409:e.code='evidence_conflict'
            raise
        return annotation(reader_repo.find_annotation(db,result['id']))
    return mutate(request,body,idempotency_key,op)
@router.patch('/papers/{pid}/annotations/{ident}')
def edit_note(pid:int,ident:str,body:ExternalPatch,request:Request,idempotency_key:str|None=Header(None)):
    auth.require(request,'annotations:write',pid)
    def op(db):
        row=reader_repo.find_annotation(db,ident)
        if row is None or row['paper_id']!=pid:raise ServiceError(404,'批注不存在')
        if etag(row)!=body.expected_etag:raise ServiceError(409,'批注已变化，请刷新后重试',code='annotation_conflict')
        reader.edit_annotation(db,ident,AnnotationPatch(**body.model_dump(exclude={'expected_etag'},exclude_unset=True)))
        return annotation(reader_repo.find_annotation(db,ident))
    return mutate(request,body,idempotency_key,op)

@router.get('/papers/{pid}/annotations/{ident}')
def note(pid:int,ident:str,request:Request):
    auth.require(request,'annotations:read',pid)
    row=reader_repo.find_annotation(request.app.state.db,ident)
    if row is None or row['paper_id']!=pid:raise ServiceError(404,'批注不存在')
    return annotation(row)

from .frontier import ExternalTopic,Submission
from ..frontier import service as frontier

def frontier_auth(request,scope):
    grant=auth.require(request,scope)
    # A paper whitelist cannot authorize a library-wide topic/report view.
    return grant

@router.get('/frontier/topics')
def frontier_topics(request:Request):
    frontier_auth(request,'frontier:read')
    return {'topics':[frontier.topic_view(request.app.state.db,r) for r in request.app.state.db.execute('SELECT * FROM frontier_topics ORDER BY id DESC')]}

@router.post('/frontier/topics',status_code=201)
def create_frontier_topic(body:ExternalTopic,request:Request,idempotency_key:str|None=Header(None)):
    frontier_auth(request,'frontier:write')
    return mutate(request,body,idempotency_key,lambda db:frontier.save_topic(db,body))

@router.get('/frontier/reports')
def frontier_reports(request:Request,topic_id:int|None=None,before:int|None=None,limit:int=20):
    frontier_auth(request,'frontier:read')
    if not 1<=limit<=30:raise ServiceError(422,'分页范围无效')
    db=request.app.state.db
    rows=db.execute('SELECT p.id AS report_id,f.* FROM frontier_reports p JOIN frontier_runs f ON f.id=p.run_id WHERE (? IS NULL OR f.topic_id=?) AND (? IS NULL OR p.id<?) ORDER BY p.id DESC LIMIT ?', (topic_id,topic_id,before,before,limit+1)).fetchall()
    result={'reports':[frontier.run_view(db,r) for r in rows[:limit]],'next_cursor':rows[limit-1]['report_id'] if len(rows)>limit else None}
    db.commit();return result

@router.get('/frontier/reports/{ident}')
def frontier_report(ident:str,request:Request):
    frontier_auth(request,'frontier:read')
    db=request.app.state.db
    if not db.execute('SELECT 1 FROM frontier_reports WHERE run_id=?',(ident,)).fetchone():raise ServiceError(404,'报告不存在')
    result=frontier.run_view(db,frontier.require(db,'frontier_runs',ident));db.commit();return result

@router.post('/frontier/topics/{topic_id}/reports',status_code=201)
def submit_frontier_report(topic_id:int,body:Submission,request:Request,idempotency_key:str|None=Header(None)):
    grant=frontier_auth(request,'frontier:write')
    from .frontier import submit
    return mutate(request,body,idempotency_key,lambda db:submit(db,topic_id,body,grant['id']))


from ..research import service as research
from ..research.schemas import ArtifactWrite,KnowledgeWrite
from fastapi import Query

def scoped(request,scope,ids):
    token=request.state.external_token
    if scope not in json.loads(token['scopes_json']):raise ServiceError(403,'缺少所需 scope')
    allowed=json.loads(token['paper_ids_json']) if token['paper_ids_json'] else None
    if allowed is not None and (not ids or not set(ids)<=set(allowed)):raise ServiceError(404,'记录未授权或不存在')
    research.check_papers(request.app.state.db,ids)
    return allowed

def scope_filter(request,scope):
    token=request.state.external_token
    if scope not in json.loads(token['scopes_json']):raise ServiceError(403,'缺少所需 scope')
    return json.loads(token['paper_ids_json']) if token['paper_ids_json'] else None

@router.get('/artifacts')
async def artifact_list(request:Request,q:str=Query('',max_length=200),paper_id:int|None=None,before:int|None=None,limit:int=Query(30,ge=1,le=100)):
    return research.artifact_list(request.app.state.db,q,paper_id,before,limit,scope_filter(request,'artifacts:read'))

@router.get('/artifacts/{ident}')
async def artifact_detail(ident:str,request:Request,revision:int|None=Query(None,ge=1)):
    scope_filter(request,'artifacts:read')
    data=research.artifact_view(request.app.state.db,ident,revision);scoped(request,'artifacts:read',data['paper_ids']);return data

@router.post('/artifacts',status_code=201)
async def artifact_create(body:ArtifactWrite,request:Request,idempotency_key:str|None=Header(None)):
    scoped(request,'artifacts:write',body.paper_ids)
    return mutate(request,body,idempotency_key,lambda db:research.artifact_save(db,request.app.state.settings,body,origin='external'))

@router.patch('/artifacts/{ident}')
async def artifact_revise(ident:str,body:ArtifactWrite,request:Request,idempotency_key:str|None=Header(None)):
    scope_filter(request,'artifacts:write')
    old=research.artifact_view(request.app.state.db,ident);scoped(request,'artifacts:write',old['paper_ids']);scoped(request,'artifacts:write',body.paper_ids)
    return mutate(request,body,idempotency_key,lambda db:research.artifact_save(db,request.app.state.settings,body,ident,origin='external'))

@router.get('/knowledge/recall')
async def knowledge_recall(request:Request,q:str=Query('',max_length=200),limit:int=Query(20,ge=1,le=50)):
    return research.knowledge_list(request.app.state.db,q,limit=limit,allowed=scope_filter(request,'knowledge:read'),recall=True)

@router.post('/knowledge/candidates',status_code=201)
async def knowledge_candidate(body:KnowledgeWrite,request:Request,idempotency_key:str|None=Header(None)):
    ids=set()
    scope_filter(request,'knowledge:write')
    for source in body.sources:ids.update(research.artifact_view(request.app.state.db,source.artifact_id,source.revision)['paper_ids'])
    scoped(request,'knowledge:write',list(ids))
    return mutate(request,body,idempotency_key,lambda db:research.knowledge_save(db,body))

@router.get('/runs/{ident}/timeline')
async def external_timeline(ident:str,request:Request,after:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200)):
    scope_filter(request,'runs:read')
    row=request.app.state.db.execute('SELECT conversation_id FROM agent_runs WHERE id=?',(ident,)).fetchone()
    if not row:raise ServiceError(404,'任务不存在')
    ids=[r[0] for r in request.app.state.db.execute('SELECT paper_id FROM conversation_papers WHERE conversation_id=?',(row[0],))]
    scoped(request,'runs:read',ids)
    from ..research.events import listing
    return listing(request.app.state.db,ident,after,limit)


from fastapi import UploadFile,File,Form
from ..research import files as research_files

@router.post('/files',status_code=201)
async def upload_asset(request:Request,paper_id:int=Form(...),file:UploadFile=File(...)):
    scoped(request,'artifacts:write',[paper_id])
    data=await file.read(research_files.MAX_SIZE+1)
    with request.app.state.db:return research_files.store(request.app.state.db,request.app.state.settings,paper_id,file.filename or 'file',data)

@router.get('/files/{ident}')
async def download_asset(ident:str,request:Request):
    scope_filter(request,'artifacts:read')
    row,path=research_files.resolve(request.app.state.db,request.app.state.settings,ident);scoped(request,'artifacts:read',[row['paper_id']])
    return FileResponse(path,media_type='application/octet-stream',filename=row['filename'],headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})


from ..workbench import contexts
@router.get('/contexts')
def active_contexts(request:Request):return contexts.listing(request)
@router.get('/contexts/{ident}')
def active_context(ident:str,request:Request,expected_revision:int|None=None):return contexts.get(request,ident,expected_revision)
@router.get('/contexts/{ident}/resource')
def current_resource(ident:str,request:Request,expected_revision:int):
    ctx=contexts.get(request,ident,expected_revision);resource=ctx['resource']
    if resource.get('paper_id'):
        auth.require(request,'papers:read',resource['paper_id'])
        data=papers.paper_detail(request.app.state.db,resource['paper_id'])
        return {'context':ctx,'paper':data}
    if resource.get('report_id'):
        return {'context':ctx,'report':frontier_report(resource['report_id'],request)}
    return {'context':ctx}

from ..research.submissions import Submission
@router.post('/research-submissions',status_code=201)
def submit_research(body:Submission,request:Request,idempotency_key:str|None=Header(None)):
    scoped(request,'artifacts:write',body.artifact.paper_ids)
    for annotation in body.annotations:auth.require(request,'annotations:write',annotation.paper_id)
    if body.translation:auth.require(request,'annotations:write',body.translation.paper_id)
    from ..research.submissions import save
    return mutate(request,body,idempotency_key,lambda db:save(db,request.app.state.settings,body,request.state.external_token['id']))

@router.get('/research-submissions/{client_job_id}')
def submission_receipt(client_job_id:str,request:Request):
    scope_filter(request,'artifacts:read')
    row=request.app.state.db.execute('SELECT receipt_json FROM external_submissions WHERE token_id=? AND client_job_id=?',(request.state.external_token['id'],client_job_id)).fetchone()
    if not row:raise ServiceError(404,'本机任务尚无回执')
    receipt=json.loads(row[0]);item=research.artifact_view(request.app.state.db,receipt['artifact_id']);scoped(request,'artifacts:read',item['paper_ids']);return receipt

@router.get('/selections/{ident}')
def shared_selection(ident:str,request:Request):
    if 'context:selection' not in json.loads(request.state.external_token['scopes_json']):raise ServiceError(403,'缺少选区授权')
    row=request.app.state.db.execute('SELECT * FROM context_selections WHERE id=? AND expires_at>?',(ident,__import__('time').time())).fetchone()
    if not row:raise ServiceError(404,'分享已过期或不存在')
    contexts.get(request,row['context_id']);anchor=json.loads(row['anchor_json']);auth.require(request,'papers:read',anchor['paper_id']);return {'id':ident,'anchor':anchor,'expires_at':row['expires_at']}
