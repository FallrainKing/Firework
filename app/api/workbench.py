"""Persistent workspaces, reading drafts, image attachments and task schedules."""
import asyncio
from datetime import datetime,timedelta,timezone
import io,json,re,uuid,struct,os
from pathlib import Path
from fastapi import APIRouter,Request,HTTPException,UploadFile,File,Form
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
import pymupdf
from ..sessions.service import require_session
from .reader import linked,Context
router=APIRouter(prefix='/api/workbench',tags=['workbench'])
MAX_IMAGE=5*1024*1024

def attachment_view(row):
    return dict(row)|{'url':f"/api/workbench/images/{row['id']}"}

def image_rows(db,ids,sid,paper_id=None):
    rows=[]
    for ident in ids:
        r=db.execute('SELECT * FROM image_attachments WHERE id=?',(ident,)).fetchone()
        if r is None or r['conversation_id']!=sid or (paper_id is not None and r['paper_id']!=paper_id):raise HTTPException(400,'图片未关联当前论文会话')
        rows.append(r)
    return rows

@router.get('/recent')
async def recent(request:Request):
    return {'recent':[dict(r) for r in request.app.state.db.execute('SELECT r.paper_id,r.conversation_id,r.updated_at FROM reader_states r JOIN conversations c ON c.id=r.conversation_id WHERE c.archived=0 ORDER BY r.updated_at DESC,r.rowid DESC LIMIT 80')]}


def image_header(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=24:
        width,height=struct.unpack('!II',data[16:24]);mime='image/png'
    elif data.startswith(b'\xff\xd8'):
        offset=2;width=height=0;mime='image/jpeg'
        while offset+4<=len(data):
            if data[offset]!=255:raise ValueError('JPEG 数据格式无效')
            while offset<len(data) and data[offset]==255:offset+=1
            if offset>=len(data):break
            marker=data[offset];offset+=1
            if marker in (0xd8,0xd9) or 0xd0<=marker<=0xd7:continue
            if marker==0xda:break
            length=int.from_bytes(data[offset:offset+2],'big')
            if length<2 or offset+length>len(data):raise ValueError('JPEG 数据不完整')
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                if length<7:raise ValueError('JPEG 尺寸无效')
                height,width=struct.unpack('!HH',data[offset+3:offset+7]);break
            offset+=length
    else:raise ValueError('请选择 PNG 或 JPEG 图片')
    if not width or not height or width*height>16_000_000 or max(width,height)>8192:raise ValueError('图片不超过 1600 万像素，最长边不超过 8192')
    return mime,width,height

class Tab(BaseModel):
    paper_id:int=Field(gt=0)
    session_id:int|None=None
class Layout(BaseModel):
    left_width:int=Field(235,ge=140,le=600)
    right_width:int=Field(340,ge=140,le=600)
    left_hidden:bool=False
    right_hidden:bool=False
class Workspace(BaseModel):
    layout:Layout=Field(default_factory=Layout)
    tabs:list[Tab]=Field(default_factory=list,max_length=20)
    active_paper_id:int|None=None
    view:str=Field('read',pattern=r'^(read|compare|schedules|library)$')

@router.get('/states/{ident}')
async def workspace(ident:str,request:Request):
    if not re.fullmatch(r'[a-f0-9]{32}',ident):raise HTTPException(400,'无效工作区')
    r=request.app.state.db.execute('SELECT state_json FROM workspace_states WHERE id=?',(ident,)).fetchone()
    return json.loads(r[0]) if r else Workspace().model_dump()

@router.put('/states/{ident}')
async def save_workspace(ident:str,body:Workspace,request:Request):
    if not re.fullmatch(r'[a-f0-9]{32}',ident):raise HTTPException(400,'无效工作区')
    db=request.app.state.db
    if len({t.paper_id for t in body.tabs})!=len(body.tabs):raise HTTPException(400,'同一论文不能重复打开')
    for t in body.tabs:
        if not db.execute('SELECT 1 FROM papers WHERE id=?',(t.paper_id,)).fetchone():raise HTTPException(400,'论文不存在')
        if t.session_id is not None:linked(db,t.session_id,t.paper_id)
    if body.active_paper_id is not None and body.active_paper_id not in [t.paper_id for t in body.tabs]:raise HTTPException(400,'活动论文未打开')
    value=body.model_dump();db.execute('INSERT INTO workspace_states(id,state_json) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP',(ident,json.dumps(value)));db.commit();return value

class Draft(BaseModel):
    prompt:str=Field('',max_length=3000)
    context:Context|None=None
    attachment_ids:list[str]=Field(default_factory=list,max_length=3)

@router.get('/drafts/{sid}/{pid}')
async def draft(sid:int,pid:int,request:Request):
    db=request.app.state.db;linked(db,sid,pid)
    r=db.execute('SELECT draft_json FROM reader_drafts WHERE conversation_id=? AND paper_id=?',(sid,pid)).fetchone()
    data=json.loads(r[0]) if r else Draft().model_dump()
    data['attachments']=[attachment_view(a) for a in image_rows(db,data['attachment_ids'],sid,pid)]
    return data

@router.put('/drafts/{sid}/{pid}')
async def save_draft(sid:int,pid:int,body:Draft,request:Request):
    db=request.app.state.db;linked(db,sid,pid);image_rows(db,body.attachment_ids,sid,pid)
    if body.context and body.context.paper_id!=pid:raise HTTPException(400,'选区属于其他论文')
    db.execute('INSERT INTO reader_drafts(conversation_id,paper_id,draft_json) VALUES (?,?,?) ON CONFLICT(conversation_id,paper_id) DO UPDATE SET draft_json=excluded.draft_json,updated_at=CURRENT_TIMESTAMP',(sid,pid,json.dumps(body.model_dump(),ensure_ascii=False)));db.commit();return {'saved':True}

@router.post('/images',status_code=201)
async def upload_image(request:Request,file:UploadFile=File(...),conversation_id:int=Form(...),paper_id:int=Form(...)):
    db=request.app.state.db;linked(db,conversation_id,paper_id)
    data=await file.read(MAX_IMAGE+1)
    if len(data)>MAX_IMAGE:raise HTTPException(413,'图片不超过 5MB')
    try:
        mime,width,height=image_header(data)
        decoded=pymupdf.Pixmap(data)
        if decoded.width!=width or decoded.height!=height:raise ValueError('图片尺寸不一致')
    except (RuntimeError,OSError,ValueError) as exc:raise HTTPException(400,str(exc) if isinstance(exc,ValueError) else '图片无法读取，请转为 PNG 或 JPEG')
    ident=uuid.uuid4().hex;folder=request.app.state.settings.data_dir/'attachments';folder.mkdir(parents=True,exist_ok=True)
    path=folder/ident
    with path.open('wb') as f:f.write(data)
    path.chmod(0o600)
    if os.geteuid()==0:
        owner=request.app.state.settings.data_dir.stat()
        os.chown(folder,owner.st_uid,owner.st_gid)
        os.chown(path,owner.st_uid,owner.st_gid)
    folder.chmod(0o700)
    name=Path((file.filename or 'image').replace('\\','/')).name[:180]
    try:db.execute('INSERT INTO image_attachments(id,conversation_id,paper_id,filename,mime,size,width,height) VALUES (?,?,?,?,?,?,?,?)',(ident,conversation_id,paper_id,name,mime,len(data),width,height));db.commit()
    except Exception:path.unlink(missing_ok=True);raise
    return attachment_view(db.execute('SELECT * FROM image_attachments WHERE id=?',(ident,)).fetchone())

@router.get('/images/{ident}')
async def get_image(ident:str,request:Request):
    if not re.fullmatch(r'[a-f0-9]{32}',ident):raise HTTPException(404,'图片不存在')
    row=request.app.state.db.execute('SELECT * FROM image_attachments WHERE id=?',(ident,)).fetchone()
    if row is None:raise HTTPException(404,'图片不存在')
    return FileResponse(request.app.state.settings.data_dir/'attachments'/ident,media_type=row['mime'],headers={'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'})

class Schedule(BaseModel):
    title:str=Field(min_length=1,max_length=160)
    conversation_id:int
    prompt:str=Field(min_length=1,max_length=3000)
    interval_hours:int=Field(24,ge=1,le=8760)
    enabled:bool=False
class Enable(BaseModel):enabled:bool

def next_time(hours):return (datetime.now(timezone.utc)+timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
@router.get('/schedules')
async def schedules(request:Request):
    return {'schedules':[dict(r) for r in request.app.state.db.execute('SELECT s.*,c.title AS session_title FROM research_schedules s JOIN conversations c ON c.id=s.conversation_id ORDER BY s.id DESC')]}
@router.post('/schedules',status_code=201)
async def create_schedule(body:Schedule,request:Request):
    db=request.app.state.db;session=require_session(db,body.conversation_id)
    if not body.title.strip() or not body.prompt.strip():raise HTTPException(400,'任务名称和要求不能为空')
    if session['archived']:raise HTTPException(400,'请选择未归档的会话')
    if session['skill']=='paper_import':raise HTTPException(400,'导入任务不能定时重复执行')
    if session['skill'] in ('paper_read','paper_review','paper_compare'):
        papers=db.execute('SELECT p.pdf_path FROM papers p JOIN conversation_papers cp ON cp.paper_id=p.id WHERE cp.conversation_id=?',(body.conversation_id,)).fetchall()
        if not papers or any(not p['pdf_path'] for p in papers):raise HTTPException(400,'请先为关联论文补充 PDF 全文')
    cur=db.execute('INSERT INTO research_schedules(title,conversation_id,prompt,interval_hours,enabled,next_at) VALUES (?,?,?,?,?,?)',(body.title.strip(),body.conversation_id,body.prompt,body.interval_hours,body.enabled,next_time(body.interval_hours)));db.commit();return dict(db.execute('SELECT * FROM research_schedules WHERE id=?',(cur.lastrowid,)).fetchone())
@router.patch('/schedules/{ident}')
async def enable_schedule(ident:int,body:Enable,request:Request):
    db=request.app.state.db;r=db.execute('SELECT * FROM research_schedules WHERE id=?',(ident,)).fetchone()
    if r is None:raise HTTPException(404,'定时任务不存在')
    db.execute('UPDATE research_schedules SET enabled=?,next_at=? WHERE id=?',(body.enabled,next_time(r['interval_hours']),ident));db.commit();return {'saved':True}

async def fire_schedule(ident,request):
    from .agent import create_run,RunCreate
    db=request.app.state.db;r=db.execute('SELECT * FROM research_schedules WHERE id=?',(ident,)).fetchone()
    if r is None:raise HTTPException(404,'定时任务不存在')
    run=await create_run(RunCreate(conversation_id=r['conversation_id'],prompt=r['prompt']),request)
    db.execute('UPDATE research_schedules SET last_run_id=?,next_at=? WHERE id=?',(run['id'],next_time(r['interval_hours']),ident));db.commit();return run
@router.post('/schedules/{ident}/run',status_code=202)
async def run_schedule(ident:int,request:Request):return await fire_schedule(ident,request)

async def schedule_loop(app):
    from types import SimpleNamespace
    while True:
        await asyncio.sleep(60)
        db=app.state.db
        for row in db.execute("SELECT * FROM research_schedules WHERE enabled=1 AND next_at<=datetime('now')").fetchall():
            # Advance before dispatch: a restart must never replay billed work.
            db.execute('UPDATE research_schedules SET next_at=? WHERE id=?',(next_time(row['interval_hours']),row['id']));db.commit()
            try:await fire_schedule(row['id'],SimpleNamespace(app=app))
            except HTTPException:pass
