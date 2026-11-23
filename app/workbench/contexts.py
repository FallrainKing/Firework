"""Explicitly shared, short-lived application context; never browser history or drafts."""
import json,time,uuid
from typing import Literal
from pydantic import BaseModel,Field,ConfigDict
from fastapi import APIRouter,Request
from ..core.errors import ServiceError

router=APIRouter(prefix='/api/workbench/contexts',tags=['page context'])
class Resource(BaseModel):
    model_config=ConfigDict(extra='forbid')
    paper_id:int|None=Field(None,ge=1)
    document_version_id:str|None=Field(None,max_length=64)
    file_hash:str|None=Field(None,pattern='^[a-f0-9]{64}$')
    session_id:int|None=Field(None,ge=1)
    topic_id:int|None=Field(None,ge=1)
    report_id:str|None=Field(None,pattern='^[a-f0-9]{32}$')
    artifact_id:str|None=Field(None,pattern='^[a-f0-9]{32}$')
    collection_id:int|None=Field(None,ge=1)
class ContextWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    workspace_id:str=Field(pattern='^[a-f0-9]{32}$')
    revision:int=Field(ge=1)
    view:Literal['home','reader','frontier','compare','library','research','settings','schedules','skills']='home'
    resource:Resource=Field(default_factory=Resource)
    page:int|None=Field(None,ge=1,le=300)
    panel:str|None=Field(None,max_length=30)
    visibility:Literal['visible','hidden','closed']='visible'
    has_focus:bool=False
    shared:bool=False

def validate(db,settings,body):
    r=body.resource
    if r.paper_id:
        if not db.execute('SELECT 1 FROM papers WHERE id=? AND deleted_at IS NULL',(r.paper_id,)).fetchone():raise ServiceError(404,'论文不存在')
    if r.document_version_id:
        if not r.paper_id:raise ServiceError(422,'文件版本必须关联论文')
        from ..documents.service import version
        v=version(db,r.paper_id,r.document_version_id)
        if r.file_hash and r.file_hash!=v['file_hash']:raise ServiceError(409,'PDF版本与哈希不匹配')
        if body.page and body.page>v['page_count']:raise ServiceError(422,'原文页码无效')
    if r.file_hash and not r.document_version_id:
        if not r.paper_id:raise ServiceError(422,'文件哈希必须关联论文')
        from ..reader import service,pages
        _,digest=pages.pdf_file(settings,service.paper(db,r.paper_id))
        if digest!=r.file_hash:raise ServiceError(409,'PDF哈希不匹配')
    if r.session_id:
        if not db.execute('SELECT 1 FROM conversations WHERE id=?',(r.session_id,)).fetchone():raise ServiceError(404,'会话不存在')
        if r.paper_id and not db.execute('SELECT 1 FROM conversation_papers WHERE conversation_id=? AND paper_id=?',(r.session_id,r.paper_id)).fetchone():raise ServiceError(409,'会话不属于论文')
    if r.topic_id and not db.execute('SELECT 1 FROM frontier_topics WHERE id=?',(r.topic_id,)).fetchone():raise ServiceError(404,'前沿主题不存在')
    if r.report_id and not db.execute('SELECT 1 FROM frontier_runs WHERE id=? AND topic_id=?',(r.report_id,r.topic_id)).fetchone():raise ServiceError(404,'报告不属于主题')
    if r.artifact_id and not db.execute('SELECT 1 FROM research_artifacts WHERE id=? AND archived=0',(r.artifact_id,)).fetchone():raise ServiceError(404,'产物不存在')
    if r.collection_id and not db.execute('SELECT 1 FROM paper_collections WHERE id=?',(r.collection_id,)).fetchone():raise ServiceError(404,'分类不存在')
    if body.view=='reader' and not r.paper_id:raise ServiceError(422,'阅读页缺少论文')

@router.post('',status_code=201)
def register(request:Request):
    ident=uuid.uuid4().hex;db=request.app.state.db
    with db:
        db.execute('DELETE FROM context_selections WHERE expires_at<?',(int(time.time()),))
        db.execute('DELETE FROM workspace_contexts WHERE expires_at<?',(int(time.time())-86400,))
        db.execute('INSERT INTO workspace_contexts(id,auth_version,auth_session_hash) VALUES (?,?,?)',(ident,request.state.auth_user.get('session_version',0) if request.state.auth_user else 0,request.state.auth_user.get('token_hash','') if request.state.auth_user else ''))
    return {'id':ident,'revision':0}

@router.put('/{ident}')
def update(ident:str,body:ContextWrite,request:Request):
    db=request.app.state.db;row=db.execute('SELECT * FROM workspace_contexts WHERE id=?',(ident,)).fetchone()
    if not row:raise ServiceError(404,'窗口上下文不存在')
    validate(db,request.app.state.settings,body)
    now=int(time.time());old=json.loads(row['payload_json']);new=body.model_dump()
    changed=any(old.get(k)!=new.get(k) for k in ('view','resource','page','panel'))
    revision=row['context_revision']+int(changed)
    with db:
        cur=db.execute('UPDATE workspace_contexts SET payload_json=?,revision=?,context_revision=?,shared=?,observed_at=?,expires_at=? WHERE id=? AND revision<?',(body.model_dump_json(),body.revision,revision,int(body.shared and body.visibility!='closed'),now,now+(45 if body.visibility=='visible' else 0),ident,body.revision))
        if not cur.rowcount:raise ServiceError(409,'上下文修订已变化')
    return {'id':ident,'revision':body.revision,'observed_at':now,'expires_at':now+(45 if body.visibility=='visible' else 0)}

def permitted(request,row):
    token=context_token(request);ids=json.loads(token['paper_ids_json']) if token['paper_ids_json'] else None
    value=json.loads(row['payload_json']);resource=value.get('resource',{})
    if ids is not None:
        pid=resource.get('paper_id')
        if not pid or pid not in ids or value.get('view')!='reader':return False
        # Other resource references must not leak via a paper-only grant.
        if any(resource.get(k) for k in ('topic_id','report_id','artifact_id')):return False
    if row['auth_session_hash']:
        active=request.app.state.auth_store.db.execute('SELECT 1 FROM auth_sessions WHERE token_hash=? AND revoked=0 AND expires_at>?',(row['auth_session_hash'],int(time.time()))).fetchone()
        if not active:return False
    return bool(row['shared'])

def listing(request):
    context_token(request)
    rows=request.app.state.db.execute('SELECT * FROM workspace_contexts WHERE shared=1 AND expires_at>? ORDER BY observed_at DESC LIMIT 100',(int(time.time()),)).fetchall()
    return {'contexts':[view(request,r) for r in rows if permitted(request,r)],'automatic_target':False}

def view(request,row):
    value=json.loads(row['payload_json']);return {'context_id':row['id'],'revision':row['context_revision'],'view':value.get('view'),'resource':value.get('resource',{}),'reading':{'page':value.get('page'),'panel':value.get('panel')},'visibility':value.get('visibility'),'has_focus':value.get('has_focus',False),'observed_at':row['observed_at'],'expires_at':row['expires_at'],'state':'current' if row['expires_at']>int(time.time()) else 'stale'}

def get(request,ident,revision=None):
    context_token(request);row=request.app.state.db.execute('SELECT * FROM workspace_contexts WHERE id=?',(ident,)).fetchone()
    if not row or not permitted(request,row):raise ServiceError(404,'上下文未共享或无权读取')
    if row['expires_at']<=int(time.time()):raise ServiceError(409,'上下文已过期，不能视为当前页面',code='context_stale')
    if revision is not None and revision!=row['context_revision']:raise ServiceError(409,'页面已变化，请重新读取上下文',code='context_changed')
    value=ContextWrite.model_validate_json(row['payload_json']);validate(request.app.state.db,request.app.state.settings,value)
    return view(request,row)

from ..reader.schemas import Context
@router.post('/{ident}/selections',status_code=201)
def share_selection(ident:str,body:Context,request:Request):
    row=request.app.state.db.execute('SELECT * FROM workspace_contexts WHERE id=?',(ident,)).fetchone()
    if not row or not row['shared'] or row['expires_at']<=int(time.time()):raise ServiceError(409,'请先共享当前页面')
    current=json.loads(row['payload_json']).get('resource',{})
    if current.get('paper_id')!=body.paper_id or current.get('file_hash')!=body.file_version:raise ServiceError(409,'选区与当前页面不一致')
    from ..reader.anchors import locate
    anchor=locate(request.app.state.db,request.app.state.settings,body)
    if anchor['status']!='located':raise ServiceError(422,'选区无法定位')
    ident_new=uuid.uuid4().hex;expires=int(time.time())+300
    with request.app.state.db:request.app.state.db.execute('INSERT INTO context_selections VALUES (?,?,?,?)',(ident_new,ident,json.dumps(anchor),expires))
    return {'id':ident_new,'expires_at':expires}


def context_token(request):
    token=request.state.external_token
    if 'context:read' not in json.loads(token['scopes_json']):raise ServiceError(403,'缺少页面上下文授权')
    return token
