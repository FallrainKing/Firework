import json
from fastapi import APIRouter,Request,Query
from pydantic import BaseModel,Field
from ..core.errors import ServiceError
from . import service as s
from .schemas import TopicCreate,TopicPatch,Trigger,Decision,BatchDecision,Report

router=APIRouter(prefix='/api/frontier',tags=['frontier'])
internal=APIRouter(prefix='/api/internal/frontier',tags=['internal'])

@router.get('/capabilities')
async def capabilities(request:Request):
    from ..skills.service import execution_policy
    try:policy=execution_policy(request.app.state.db,'frontier_monitor');ready=True
    except ValueError:policy={};ready=False
    return {'sources':['arxiv','crossref','github'],'skill':'frontier_monitor','ready':ready,'policy':{k:policy.get(k) for k in ('version_id','max_calls','max_budget_usd','max_output_tokens')},'mode':'background','reading_skills':[{'id':'kelip-paper-reading','status':'requires_material_and_vision_adapter'},{'id':'nature-reader','status':'requires_fulltext_adapter'}]}

@router.get('/topics')
async def topics(request:Request):
    db=request.app.state.db;s.reconcile(db);s.sync_existing_library(db)
    return {'topics':[s.topic_view(db,r) for r in db.execute('SELECT * FROM frontier_topics ORDER BY id DESC')]}

@router.post('/topics',status_code=201)
async def create(body:TopicCreate,request:Request):return s.save_topic(request.app.state.db,body)

@router.patch('/topics/{ident}')
async def patch(ident:int,body:TopicPatch,request:Request):return s.save_topic(request.app.state.db,body,ident)

@router.post('/topics/{ident}/runs',status_code=202)
async def trigger(ident:int,body:Trigger,request:Request):return await s.trigger(request.app.state.db,request.app.state,ident,body.request_key)

@router.get('/topics/{ident}/runs')
async def runs(ident:int,request:Request):
    db=request.app.state.db;s.require(db,'frontier_topics',ident);s.reconcile(db)
    out=[s.run_view(db,r) for r in db.execute('SELECT * FROM frontier_runs WHERE topic_id=? ORDER BY created_at DESC,id DESC LIMIT 50',(ident,))];db.commit();return {'runs':out}

@router.post('/runs/{ident}/cancel')
async def cancel(ident:str,request:Request):
    from ..agent.service import cancel_run
    db=request.app.state.db;r=s.require(db,'frontier_runs',ident)
    if not r['agent_run_id']:raise ServiceError(409,'分派中，请稍后重试')
    await cancel_run(db,r['agent_run_id'],request.app.state);s.reconcile(db)
    return s.run_view(db,s.require(db,'frontier_runs',ident))

@router.post('/runs/{ident}/discussion')
async def discussion(ident:str,request:Request):
    from ..sessions.service import create_session
    from ..sessions.schemas import SessionCreate
    db=request.app.state.db;r=s.require(db,'frontier_runs',ident)
    if not r['report_md'] or r['status'] not in ('succeeded','partial'):raise ServiceError(409,'报告尚未完成')
    if r['discussion_session_id']:return {'session_id':r['discussion_session_id']}
    evidence=[{'title':json.loads(x['snapshot_json']).get('title'),'evidence_id':x['id'],'url':json.loads(x['snapshot_json']).get('url')} for x in db.execute('SELECT * FROM frontier_evidence WHERE run_id=? LIMIT 10',(ident,))]
    prompt=('讨论前沿报告 '+ident+'。材料仅限已保存的摘要/元数据，不代表全文阅读。报告：'+r['report_md'][:1800]+'\n证据：'+s.dump(evidence))[:3000]
    sid=create_session(db,SessionCreate(template_id='chat',title='前沿报告讨论 · '+r['created_at'],starting_prompt=prompt))['session']['id']
    db.execute('UPDATE frontier_runs SET discussion_session_id=? WHERE id=?',(sid,ident));db.commit()
    return {'session_id':sid}

@router.get('/candidates')
async def candidates(request:Request,topic_id:int|None=None,before:str|None=Query(None,pattern=r'^\d+:\d+$')):
    rows=s.items(request.app.state.db,topic_id,before,51)
    return {'items':rows[:50],'next_cursor':str(rows[49]['id'])+':'+str(rows[49]['topic_id']) if len(rows)>50 else None}

@router.post('/topics/{topic_id}/items/{entity_id}/decision')
async def decision(topic_id:int,entity_id:int,body:Decision,request:Request):return await s.decide(request.app.state.db,request.app.state,topic_id,entity_id,body)

@router.post('/decisions/batch')
async def batch(body:BatchDecision,request:Request):
    from pydantic import ValidationError
    results=[]
    for item in body.items:
        try:
            tid=int(item['topic_id']);eid=int(item['entity_id']);result=await s.decide(request.app.state.db,request.app.state,tid,eid,Decision(**item['decision']));results.append({'entity_id':eid,**result})
        except (ServiceError,ValidationError,KeyError,ValueError) as e:results.append({'entity_id':item.get('entity_id'),'saved':False,'error':str(getattr(e,'detail','无效操作'))})
    return {'results':results}

@router.get('/reports')
async def reports(request:Request,topic_id:int|None=None,before:int|None=None,limit:int=Query(15,ge=1,le=30)):
    db=request.app.state.db;s.reconcile(db);clauses=['1=1'];args=[]
    if topic_id:clauses.append('f.topic_id=?');args.append(topic_id)
    if before:clauses.append('p.id<?');args.append(before)
    rows=db.execute('SELECT p.id AS report_id,p.version,f.*,t.title AS topic_title,coalesce(rr.version,0)>=p.version AS is_read FROM frontier_reports p JOIN frontier_runs f ON f.id=p.run_id JOIN frontier_topics t ON t.id=f.topic_id LEFT JOIN frontier_report_reads rr ON rr.run_id=f.id WHERE '+' AND '.join(clauses)+' ORDER BY p.id DESC LIMIT ?',(*args,limit+1)).fetchall()
    out=[{**s.run_view(db,r),'report_id':r['report_id'],'topic_title':r['topic_title'],'is_read':bool(r['is_read']),'version':r['version']} for r in rows[:limit]];db.commit()
    return {'reports':out,'next_cursor':rows[limit-1]['report_id'] if len(rows)>limit else None}

@router.patch('/reports/{run_id}/read-state')
async def read(run_id:str,request:Request):
    db=request.app.state.db
    p=db.execute('SELECT max(version) FROM frontier_reports WHERE run_id=?',(run_id,)).fetchone()[0]
    if not p:raise ServiceError(404,'报告不存在')
    db.execute('INSERT OR REPLACE INTO frontier_report_reads(run_id,version) VALUES (?,?)',(run_id,p));db.commit();return {'saved':True}

@router.get('/projects')
async def projects(request:Request,collection_id:int|None=None,q:str=Query('',max_length=200)):
    db=request.app.state.db
    rows=db.execute('SELECT p.* FROM projects p WHERE instr(lower(p.title||p.description),lower(?))>0 AND (? IS NULL OR EXISTS(SELECT 1 FROM project_collection_items c WHERE c.project_id=p.id AND c.collection_id=?)) ORDER BY p.id DESC LIMIT 200',(q,collection_id,collection_id)).fetchall()
    return {'projects':[{**dict(r),'metadata':json.loads(r['metadata_json'])} for r in rows]}

class Search(BaseModel):
    source:str
    query:str=Field(min_length=1,max_length=200)


def bound(request):return s.authenticated_run(request.app.state.db,request.app.state.settings,request.headers.get('x-research-run-id',''),request.headers.get('x-research-tool-token',''))

@internal.post('/context')
async def context(request:Request):return s.context(request.app.state.db,bound(request))

@internal.post('/search')
async def search(body:Search,request:Request):
    from .sources import search
    db=request.app.state.db;r=bound(request);ctx=s.context(db,r)
    if body.source not in ctx['config']['sources']:raise ServiceError(400,'来源不在配置中')
    coverage=json.loads(r['coverage_json'])
    if len(coverage)>=6:raise ServiceError(429,'本轮检索次数已达上限')
    w=ctx['windows'][body.source]
    key=s.hashlib.sha256(body.query.strip().casefold().encode()).hexdigest()
    page=db.execute('SELECT * FROM frontier_pages WHERE topic_id=? AND source=? AND revision=? AND query_key=?',(r['topic_id'],body.source,r['revision'],key)).fetchone()
    offset=0
    if page:w={'start':page['window_start'],'end':page['window_end']};offset=page['next_offset']
    try:result=await search(body.source,body.query,w['start'],w['end'],ctx['config']['max_results'],offset)

    except Exception as e:
        r=bound(request)
        return s.ingest(db,r,body.source,body.query,error='来源请求失败：'+type(e).__name__)
    r=bound(request)
    result['query_key']=key
    return s.ingest(db,r,body.source,body.query,result)

@internal.post('/report')
async def report(body:Report,request:Request):return s.save_report(request.app.state.db,bound(request),body)
