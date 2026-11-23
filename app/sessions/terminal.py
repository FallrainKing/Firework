"""Create an explicit terminal branch. Browser never chooses host paths or commands."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
import httpx
from pydantic import BaseModel,Field
from ..agent import runner_client
from ..core.errors import ServiceError
from ..runner_config import connections
from .service import require_session,session_view
from . import repository as repo

class Start(BaseModel):
    controller_id:str=Field(pattern='^[a-f0-9]{32}$')
    confirmed_new_session:bool=False

class Control(BaseModel):
    controller_id:str=Field(pattern='^[a-f0-9]{32}$')
    generation:str=Field(pattern='^[a-f0-9]{32}$')

class Input(Control):
    data:str=Field(min_length=1,max_length=32768)
    request_key:str=Field(pattern='^[a-f0-9]{32}$')

class Resize(Control):
    cols:int=Field(ge=20,le=240)
    rows:int=Field(ge=10,le=100)

async def call(method,path,**kwargs):
    try:
        async with runner_client.client() as c:r=await c.request(method,path,timeout=20,**kwargs)
        if r.status_code>=400:
            if r.status_code in (404,409,422,429,503):raise ServiceError(r.status_code,str(r.json().get('detail','隔离终端不可用'))[:180])
            raise ServiceError(503,'隔离终端运行服务异常')
        return r.json()
    except (httpx.HTTPError,ValueError):raise ServiceError(503,'隔离终端运行服务不可用') from None

def require_terminal(db,ident):
    row=require_session(db,ident)
    if row['execution_mode']!='terminal':raise ServiceError(409,'请先创建独立终端会话')
    return row


def papers_snapshot(state,ident,pids):
    folder=state.settings.data_dir/'agent/terminals'/str(ident)/'papers'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if folder.is_symlink():raise ServiceError(409,'资料目录不可使用链接')
    manifest=[];total=0
    for pid in pids:
        paper=state.db.execute('SELECT * FROM papers WHERE id=? AND deleted_at IS NULL',(pid,)).fetchone()
        if not paper or not paper['pdf_path']:continue
        path=Path(paper['pdf_path']);root=state.settings.data_dir.resolve()
        try:path.resolve().relative_to(root)
        except ValueError:raise ServiceError(409,'论文原文不在当前账号资料目录中') from None
        if path.is_symlink() or not path.is_file():raise ServiceError(409,'论文原文不可读取')
        size=path.stat().st_size;total+=size
        if size>100*1024*1024 or total>250*1024*1024:raise ServiceError(422,'终端论文快照过大，请减少关联材料')
        target=folder/f'{pid}.pdf'
        if target.is_symlink():raise ServiceError(409,'资料文件不可使用链接')
        # Re-creation is explicit; never silently replace a terminal's existing snapshot.
        if not target.exists():
            temp=folder/('.'+uuid.uuid4().hex+'.part')
            try:
                with path.open('rb') as src,temp.open('xb') as dst:shutil.copyfileobj(src,dst)
                os.chmod(temp,0o400);temp.replace(target)
            finally:temp.unlink(missing_ok=True)
        with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        version=state.db.execute('SELECT v.id FROM document_versions v JOIN paper_documents d ON d.id=v.document_id WHERE d.paper_id=? AND v.file_hash=?',(pid,digest)).fetchone()
        manifest.append({'paper_id':pid,'file':target.name,'sha256':digest,'document_version_id':version[0] if version else None})
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False))


async def start(state,ident,body):
    db=state.db;original=require_session(db,ident)
    if original['archived']:raise ServiceError(409,'会话已归档')
    if not body.confirmed_new_session:raise ServiceError(422,'请确认创建不继承旧聊天的独立终端会话')
    ready=await call('GET','/terminal-capabilities')
    if not ready.get('available'):raise ServiceError(503,ready.get('reason') or '隔离终端尚未配置')
    if original['execution_mode']=='terminal':row=original
    else:
        row=db.execute("SELECT * FROM conversations WHERE parent_session_id=? AND execution_mode='terminal' ORDER BY id DESC LIMIT 1",(ident,)).fetchone()
        if not row:
            snap=connections.snapshot(db,state.settings,bound=original['runner_connection_json'])
            with db:
                cur=repo.insert_session(db,title=original['title'][:135]+' · 隔离终端',kind=original['kind'],skill='chat',template_id=None,category_id=original['category_id'],native_session_id=str(uuid.uuid4()),draft_prompt='',skill_version_id=None)
                child=cur.lastrowid
                db.execute("UPDATE conversations SET execution_mode='terminal',parent_session_id=?,runner_connection_json=?,entry_context=? WHERE id=?",(ident,json.dumps(snap),original['entry_context'],child))
                repo.link_papers(db,child,repo.paper_ids(db,ident))
                db.execute('INSERT INTO native_terminals(conversation_id) VALUES (?)',(child,))
            row=require_session(db,child)
    snap=connections.snapshot(db,state.settings,bound=row['runner_connection_json'])
    secret=connections.materialize(db,state.settings,snap)
    papers_snapshot(state,row['id'],repo.paper_ids(db,row['id']))
    result=await call('POST',f"/terminals/{row['id']}/start",json={'controller_id':body.controller_id,'connection_snapshot':{k:v for k,v in snap.items() if k!='mode'} if snap.get('mode')=='custom' else None,'connection_secret':secret})
    return result|{'session':session_view(db,row)}
