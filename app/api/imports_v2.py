"""Manage source submissions; actual import is invoked by the existing Agent."""
import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import uuid
from typing import Literal
from fastapi import APIRouter,File,Form,HTTPException,Request,UploadFile
from pydantic import BaseModel,Field
from ..core.db import get_conn
from ..paper_sources import normalize_doi,public_url,MAX_PDF_BYTES
from ..ingest.metadata import extract_arxiv_id
from ..import_service import process_import
from ..sessions.schemas import SessionCreate
from ..sessions.service import create_session

router=APIRouter(prefix='/api/imports',tags=['imports'])
internal=APIRouter(prefix='/api/internal',tags=['internal'])

def import_view(row):
    return {k:row[k] for k in ('id','channel','source_value','original_filename','status','paper_id','conversation_id','run_id','message','error','created_at')}

def validate_targets(db,collection_id,target):
    if collection_id and not db.execute('SELECT 1 FROM paper_collections WHERE id=?',(collection_id,)).fetchone():raise HTTPException(400,'分类不存在')
    if target and not db.execute('SELECT 1 FROM papers WHERE id=?',(target,)).fetchone():raise HTTPException(400,'目标论文不存在')

async def start_import(ident,request):
    from ..agent.schemas import RunCreate
    from ..agent.service import create_run
    db=request.app.state.db;row=db.execute('SELECT * FROM import_requests WHERE id=?',(ident,)).fetchone()
    if row['status'] in ('completed','running'):return import_view(row)
    if row['run_id']:
        active=db.execute('SELECT status FROM agent_runs WHERE id=?',(row['run_id'],)).fetchone()
        if active and active['status'] in ('queued','running'):return import_view(row)
    sid=row['conversation_id']
    if sid is None:
        result=create_session(db,SessionCreate(template_id='import',title='导入：'+(row['original_filename'] or row['source_value'])[:100]))
        sid=result['session']['id'];db.execute('UPDATE import_requests SET conversation_id=? WHERE id=?',(sid,ident));db.commit()
    try:
        run=await create_run(RunCreate(conversation_id=sid,prompt=f'请执行已授权的论文入库请求 {ident}。调用 paper_import 工具一次，按工具结果告知是否取得全文，不要编造。'),request.app.state)
    except HTTPException as exc:
        db.execute("UPDATE import_requests SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(exc.detail)[:250],ident));db.commit()
        return import_view(db.execute('SELECT * FROM import_requests WHERE id=?',(ident,)).fetchone())
    db.execute("UPDATE import_requests SET status='pending',run_id=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",(run['id'],ident));db.commit()
    return import_view(db.execute('SELECT * FROM import_requests WHERE id=?',(ident,)).fetchone())

class Source(BaseModel):
    channel:Literal['auto','arxiv','doi','url']='auto'
    value:str=Field(min_length=1,max_length=2000)
    request_key:str=Field(default_factory=lambda:uuid.uuid4().hex,max_length=80)
    collection_id:int|None=None
    target_paper_id:int|None=None

@router.post('/source',status_code=202)
async def source(body:Source,request:Request):
    db=request.app.state.db;value=body.value.strip();channel=body.channel
    prior=db.execute('SELECT * FROM import_requests WHERE request_key=?',(body.request_key,)).fetchone()
    if prior:
        if prior['source_value']!=value or (channel!='auto' and prior['channel']!=channel) or prior['collection_id']!=body.collection_id or prior['target_paper_id']!=body.target_paper_id:raise HTTPException(409,'请求编号已用于其他导入参数')
        return import_view(prior)
    validate_targets(db,body.collection_id,body.target_paper_id)
    try:
        if channel=='auto':
            try:extract_arxiv_id(value);channel='arxiv'
            except ValueError:
                try:normalize_doi(value);channel='doi'
                except ValueError:channel='url'
        if channel=='arxiv':extract_arxiv_id(value)
        elif channel=='doi':normalize_doi(value)
        else:await public_url(value)
    except ValueError as e:raise HTTPException(400,str(e))
    ident=uuid.uuid4().hex
    db.execute('INSERT INTO import_requests(id,request_key,channel,source_value,collection_id,target_paper_id) VALUES (?,?,?,?,?,?)',(ident,body.request_key,channel,value,body.collection_id,body.target_paper_id));db.commit()
    return await start_import(ident,request)

@router.post('/upload',status_code=202)
async def upload(request:Request,file:UploadFile=File(...),request_key:str=Form(...),collection_id:int|None=Form(None),target_paper_id:int|None=Form(None)):
    if not 1<=len(request_key)<=80:raise HTTPException(400,'无效请求编号')
    db=request.app.state.db
    prior=db.execute('SELECT * FROM import_requests WHERE request_key=?',(request_key,)).fetchone()
    if prior:
        digest=hashlib.sha256();size=0
        while block:=await file.read(1024*1024):
            size+=len(block)
            if size>MAX_PDF_BYTES:raise HTTPException(413,'PDF 超过 30MB 限额')
            digest.update(block)
        if prior['channel']!='upload' or digest.hexdigest()!=prior['file_hash'] or prior['collection_id']!=collection_id or prior['target_paper_id']!=target_paper_id:raise HTTPException(409,'请求编号已用于其他文件或分类')
        return import_view(prior)
    validate_targets(db,collection_id,target_paper_id)
    if not (file.filename or '').lower().endswith('.pdf'):raise HTTPException(400,'请选择 PDF 文件')
    ident=uuid.uuid4().hex;folder=request.app.state.settings.data_dir/'imports';folder.mkdir(parents=True,exist_ok=True);path=folder/(ident+'.pdf');digest=hashlib.sha256();size=0
    try:
        with path.open('wb') as out:
            while block:=await file.read(1024*1024):
                size+=len(block)
                if size>MAX_PDF_BYTES:raise HTTPException(413,'PDF 超过 30MB 限额')
                if size==len(block) and not block[:1024].lstrip().startswith(b'%PDF-'):raise HTTPException(400,'文件不是有效 PDF')
                digest.update(block);out.write(block)
        if not size:raise HTTPException(400,'PDF 文件为空')
        filename=Path((file.filename or 'upload.pdf').replace('\\','/')).name[:200]
        db.execute("INSERT INTO import_requests(id,request_key,channel,source_value,original_filename,file_hash,collection_id,target_paper_id) VALUES (?,?,'upload',?,?,?,?,?)",(ident,request_key,'uploaded_pdf',filename,digest.hexdigest(),collection_id,target_paper_id));db.commit()
    except Exception:path.unlink(missing_ok=True);raise
    return await start_import(ident,request)

@router.get('')
async def list_imports(request:Request):
    return {'imports':[import_view(r) for r in request.app.state.db.execute('SELECT * FROM import_requests ORDER BY created_at DESC,rowid DESC LIMIT 40')]}

@router.get('/{ident}')
async def get_import(ident:str,request:Request):
    row=request.app.state.db.execute('SELECT * FROM import_requests WHERE id=?',(ident,)).fetchone()
    if row is None:raise HTTPException(404,'入库请求不存在')
    out=import_view(row)
    if row['run_id']:
        run=request.app.state.db.execute('SELECT status,error FROM agent_runs WHERE id=?',(row['run_id'],)).fetchone()
        if run and run['status']=='failed' and row['status'] not in ('completed','running'):out.update(status='failed',error=row['error'] or run['error'])
    return out

@router.post('/{ident}/retry')
async def retry(ident:str,request:Request):
    if not request.app.state.db.execute('SELECT 1 FROM import_requests WHERE id=?',(ident,)).fetchone():raise HTTPException(404,'入库请求不存在')
    return await start_import(ident,request)

@internal.post('/imports/{ident}/execute')
async def execute(ident:str,request:Request):
    token_file=request.app.state.settings.data_dir/'agent'/'internal-token'
    try:expected=token_file.read_text().strip()
    except OSError:raise HTTPException(403,'Internal tool unavailable')
    if not hmac.compare_digest(request.headers.get('x-research-tool-token',''),expected):raise HTTPException(403,'Internal tool authentication required')
    db=get_conn(request.app.state.settings)
    try:
        row=db.execute('SELECT * FROM import_requests WHERE id=?',(ident,)).fetchone()
        if row is None:raise HTTPException(404,'入库请求不存在')
        run=db.execute('SELECT * FROM agent_runs WHERE id=?',(request.headers.get('x-research-run-id'),)).fetchone()
        if not run or run['id']!=row['run_id'] or run['conversation_id']!=row['conversation_id'] or run['skill']!='paper_import' or run['status']!='running':raise HTTPException(403,'Import is not bound to this active Agent task')
        if row['status']=='running':raise HTTPException(409,'入库请求正在执行')
        db.execute("UPDATE import_requests SET status='running' WHERE id=? AND status IN ('pending','failed')",(ident,));db.commit()
        try:
            async with asyncio.timeout(80):
                result=await process_import(row,db,request.app.state.settings,request.app.state.embedder,request.app.state.store)
            pid=result['paper_id']
            if row['collection_id']:db.execute('INSERT OR IGNORE INTO paper_collection_items(collection_id,paper_id) VALUES (?,?)',(row['collection_id'],pid))
            db.execute('INSERT OR IGNORE INTO conversation_papers(conversation_id,paper_id) VALUES (?,?)',(row['conversation_id'],pid))
            db.execute("UPDATE import_requests SET status='completed',paper_id=?,message=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",(pid,result['message'],ident));db.commit()
            if row['channel']=='upload':(request.app.state.settings.data_dir/'imports'/(ident+'.pdf')).unlink(missing_ok=True)
            return result
        except Exception as exc:
            db.rollback();message=str(exc)[:250] if isinstance(exc,ValueError) else '来源下载或解析暂时失败：'+type(exc).__name__
            db.execute("UPDATE import_requests SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(message,ident));db.commit();raise HTTPException(502,message)
    finally:db.close()
