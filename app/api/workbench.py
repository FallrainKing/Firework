"""Schedules residual of the old workbench router — moves to app/schedules in Task 7."""
import asyncio
from datetime import datetime,timedelta,timezone
from fastapi import APIRouter,Request,HTTPException
from pydantic import BaseModel,Field
from ..core.errors import ServiceError
from ..sessions.service import require_session
router=APIRouter(prefix='/api/workbench',tags=['workbench'])

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
    from ..agent.service import create_run
    from ..agent.schemas import RunCreate
    db=request.app.state.db;r=db.execute('SELECT * FROM research_schedules WHERE id=?',(ident,)).fetchone()
    if r is None:raise HTTPException(404,'定时任务不存在')
    run=await create_run(RunCreate(conversation_id=r['conversation_id'],prompt=r['prompt']),request.app.state)
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
            # create_run now raises ServiceError; keep skipping busy/full queues.
            try:await fire_schedule(row['id'],SimpleNamespace(app=app))
            except (HTTPException,ServiceError):pass
