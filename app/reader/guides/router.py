from fastapi import APIRouter,Request,HTTPException
from pydantic import BaseModel
from ...core.errors import ServiceError
from .. import service as reader,repository as annotations_repo,pages
from ..schemas import Annotation
from . import service as s
from .schemas import GuideCreate,MaterialRequest,GuideResult,Adopt

router=APIRouter(prefix='/api/reader',tags=['reader-guides'])
internal=APIRouter(prefix='/api/internal/reader-guide',tags=['internal'])

@router.get('/guide-skills')
async def skills(request:Request):
    from ...skills.service import registry_view
    db=request.app.state.db;out=[]
    for skill in registry_view(db)['skills']:
        if skill['status']!='enabled':continue
        try:p=s.policy(db,skill['id'])
        except ServiceError:continue
        out.append({'id':skill['id'],'name':skill['name'],'version_id':p['version_id'],'max_budget_usd':p['max_budget_usd'],'max_output_tokens':p['max_output_tokens']})
    return {'skills':out,'contract':'paper-guide/v1','trigger':'explicit_user_action'}

@router.post('/papers/{pid}/guide-runs',status_code=202)
async def create(pid:int,body:GuideCreate,request:Request):return await s.create(request.app.state.db,request.app.state,pid,body)

@router.get('/papers/{pid}/guide')
async def current(pid:int,request:Request):
    try:return s.current(request.app.state.db,request.app.state.settings,pid)
    except (ValueError,OSError) as e:raise ServiceError(400,str(e)) from e

@router.get('/papers/{pid}/guides')
async def history(pid:int,request:Request):
    db=request.app.state.db;reader.paper(db,pid);s.reconcile(db,request.app.state.settings,pid)
    return {'guides':[s.view(db,r) for r in db.execute('SELECT * FROM reader_guide_tasks WHERE paper_id=? ORDER BY rowid DESC LIMIT 30',(pid,))]}

@router.post('/guide-runs/{ident}/cancel')
async def cancel(ident:str,request:Request):
    from ...agent.service import cancel_run
    db=request.app.state.db;r=s.task(db,ident)
    if not r['agent_run_id']:raise ServiceError(409,'分派中，请稍后重试')
    await cancel_run(db,r['agent_run_id'],request.app.state);s.reconcile(db,request.app.state.settings,r['paper_id'])
    return s.view(db,s.task(db,ident))

class Hidden(BaseModel):
    hidden:bool

@router.patch('/guide-runs/{ident}')
async def visibility(ident:str,body:Hidden,request:Request):
    db=request.app.state.db;s.reconcile(db,request.app.state.settings);r=s.task(db,ident)
    if r['status'] in s.ACTIVE:raise ServiceError(409,'请先停止正在运行的任务')
    db.execute('UPDATE reader_guide_tasks SET hidden=?,active=CASE WHEN ? THEN 0 ELSE active END WHERE id=?',(body.hidden,body.hidden,ident));db.commit()
    return {'saved':True}

@router.post('/guide-items/{ident}/adopt')
async def adopt(ident:str,body:Adopt,request:Request):
    db=request.app.state.db
    prior=db.execute('SELECT * FROM reader_guide_adoptions WHERE request_key=?',(body.request_key,)).fetchone()
    if prior:
        if prior['item_id']!=ident:raise ServiceError(409,'请求编号已用于其他重点')
        return reader.annotation_view(annotations_repo.find_annotation(db,prior['annotation_id']))
    item=db.execute('SELECT * FROM reader_guide_items WHERE id=?',(ident,)).fetchone()
    if not item:raise ServiceError(404,'重点不存在')
    t=s.task(db,item['task_id'])
    if pages.pdf_file(request.app.state.settings,reader.paper(db,t['paper_id']))[1]!=t['file_version']:raise ServiceError(409,'PDF 已换版，不能将旧批注采纳到新原文')
    old=db.execute('SELECT * FROM reader_annotations WHERE derived_from=?',(ident,)).fetchone()
    if old:aid=old['id']
    else:
        original=db.execute("SELECT * FROM reader_annotations WHERE guide_item_id=? AND origin='ai' ORDER BY rowid LIMIT 1",(ident,)).fetchone()
        if not original:raise ServiceError(409,'没有可采纳的批注')
        a=reader.annotation_view(original)
        data=Annotation(**{k:a[k] for k in ('paper_id','file_version','page','quote','rects','kind','content','color','conversation_id','points')})
        aid=reader.insert_annotation_record(db,data)
        db.execute("UPDATE reader_annotations SET origin='ai_adopted',derived_from=? WHERE id=?",(ident,aid))
    db.execute('INSERT INTO reader_guide_adoptions VALUES (?,?,?)',(body.request_key,ident,aid));db.commit()
    return reader.annotation_view(annotations_repo.find_annotation(db,aid))


def bound(request):return s.authorized(request.app.state.db,request.app.state.settings,request.headers.get('x-research-run-id',''),request.headers.get('x-research-tool-token',''))

@internal.post('/context')
async def context(request:Request):return s.context(request.app.state.db,request.app.state.settings,bound(request))

@internal.post('/material')
async def material(body:MaterialRequest,request:Request):
    try:return s.material(request.app.state.db,request.app.state.settings,bound(request),body.pages)
    except ValueError as e:raise ServiceError(422,str(e)) from e

@internal.post('/submit')
async def submit(body:GuideResult,request:Request):return s.submit(request.app.state.db,request.app.state.settings,bound(request),body)
