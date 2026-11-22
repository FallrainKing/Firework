"""Frontier management: facts and persistence here, research decisions in Agent."""
import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from ..core.errors import ServiceError
from . import identity
from .schemas import TopicConfig,Report


def dump(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
def now():return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
def require(db,table,ident):
    if table not in ('frontier_topics','frontier_runs','frontier_entities'):raise ValueError('Invalid table')
    row=db.execute(f'SELECT * FROM {table} WHERE id=?',(ident,)).fetchone()
    if row is None:raise ServiceError(404,'记录不存在')
    return row

def validate_collections(db,ids):
    for i in ids:
        if not db.execute('SELECT 1 FROM paper_collections WHERE id=? AND deleted_at IS NULL',(i,)).fetchone():raise ServiceError(400,'分类不存在')


def sync_existing_library(db):
    """Backfill reliable aliases without altering existing papers or reading data."""
    for p in db.execute('SELECT * FROM papers').fetchall():
        m={'kind':'paper','title':p['title'],'doi':p['doi'],'arxiv_id':p['arxiv_id'],'url':p['source_url'],'abstract':p['abstract'],'evidence_level':'library_baseline'}
        for name in ('authors','affiliations'):
            try:m[name]=json.loads(p[name] or '[]')
            except (ValueError,TypeError):m[name]=[]
        try:keys=identity.identifiers(m)
        except ValueError:continue
        matches={x[0] for k in keys for x in db.execute('SELECT entity_id FROM frontier_aliases WHERE alias=?',(k,))}
        if len(matches)>1:continue  # Conflicting existing identities need human review.
        e=db.execute('SELECT * FROM frontier_entities WHERE id=?',(next(iter(matches)),)).fetchone() if matches else None
        if e:
            if e['paper_id'] not in (None,p['id']):continue
            ident=e['id'];db.execute('UPDATE frontier_entities SET paper_id=? WHERE id=?',(p['id'],ident))
        else:
            ident=db.execute("INSERT INTO frontier_entities(kind,canonical_key,metadata_json,content_hash,paper_id) VALUES ('paper',?,?,?,?)",(keys[0],dump(m),identity.fingerprint(m),p['id'])).lastrowid
        for key in keys:db.execute('INSERT OR IGNORE INTO frontier_aliases VALUES (?,?)',(key,ident))
        db.execute('UPDATE papers SET frontier_entity_id=? WHERE id=? AND frontier_entity_id IS NULL',(ident,p['id']))
    db.commit()


def topic_view(db,r):
    d=dict(r);d['config']=json.loads(d.pop('config_json'))
    s=db.execute('SELECT * FROM research_schedules WHERE id=?',(r['schedule_id'],)).fetchone()
    d['schedule']=dict(s) if s else None
    d['pending_count']=db.execute("SELECT count(*) FROM frontier_items i JOIN frontier_entities e ON e.id=i.entity_id WHERE i.topic_id=? AND i.decision='pending' AND e.paper_id IS NULL AND e.project_id IS NULL",(r['id'],)).fetchone()[0]
    return d


def save_topic(db,body,ident=None):
    validate_collections(db,body.config.collection_ids)
    if not body.title.strip():raise ServiceError(400,'主题名称不能为空')
    from ..skills.service import ensure_builtin_skills
    from ..sessions.service import create_session
    from ..sessions.schemas import SessionCreate
    ensure_builtin_skills(db)
    config=dump(body.config.model_dump())
    if ident is None:
        # Seed template is shared with normal session machinery.
        db.execute("INSERT OR IGNORE INTO task_templates(id,name,description,kind,skill,prompt,builtin) VALUES ('frontier','前沿追踪','受限发现与报告','discovery','frontier_monitor','',1)")
        db.execute("INSERT OR IGNORE INTO task_templates(id,name,description,kind,skill,prompt,builtin) VALUES ('chat','科研讨论','围绕已有资料讨论','chat','chat','',1)")
        db.commit()
        sid=create_session(db,SessionCreate(template_id='chat',title=body.title+' · 主题讨论'))['session']['id']
        cur=db.execute('INSERT INTO frontier_topics(title,config_json,conversation_id) VALUES (?,?,?)',(body.title.strip(),config,sid));ident=cur.lastrowid;revision=1
        sc=db.execute("INSERT INTO research_schedules(title,conversation_id,prompt,interval_hours,enabled,next_at,kind,frontier_topic_id) VALUES (?,?,?,?,0,?,'frontier',?)",(body.title.strip(),sid,'按主题配置追踪',body.config.interval_hours,now(),ident)).lastrowid
        db.execute('UPDATE frontier_topics SET schedule_id=? WHERE id=?',(sc,ident))
    else:
        r=require(db,'frontier_topics',ident)
        if r['revision']!=body.revision:raise ServiceError(409,'配置已更新，请刷新')
        revision=r['revision']+1
        db.execute('UPDATE frontier_topics SET title=?,config_json=?,revision=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(body.title.strip(),config,revision,ident))
        db.execute('UPDATE research_schedules SET title=?,interval_hours=? WHERE id=?',(body.title.strip(),body.config.interval_hours,r['schedule_id']))
    db.execute('INSERT INTO frontier_topic_versions VALUES (?,?,?)',(ident,revision,config));db.commit()
    return topic_view(db,require(db,'frontier_topics',ident))


async def trigger(db,state,topic_id,key):
    require(db,'frontier_topics',topic_id)
    reconcile(db)
    prior=db.execute('SELECT * FROM frontier_runs WHERE request_key=?',(key,)).fetchone()
    if prior:
        if prior['topic_id']!=topic_id:raise ServiceError(409,'请求编号已用于其他主题')
        return run_view(db,prior)
    from ..agent.service import status_view
    health=await status_view(db)
    if not health['runner_protocol_compatible']:raise ServiceError(409,'智能体离线或版本不匹配，请先同步 Runner')
    prior=db.execute('SELECT * FROM frontier_runs WHERE request_key=?',(key,)).fetchone()
    if prior:
        if prior['topic_id']!=topic_id:raise ServiceError(409,'请求编号已用于其他主题')
        return run_view(db,prior)
    t=require(db,'frontier_topics',topic_id);cfg=json.loads(t['config_json'])
    count=db.execute("SELECT count(*) FROM frontier_runs WHERE topic_id=? AND created_at>=datetime('now','start of day')",(topic_id,)).fetchone()[0]
    if count>=cfg['daily_run_limit']:raise ServiceError(429,'今日主题执行次数已达上限，请明日再试或调整配置')
    active=db.execute("SELECT 1 FROM frontier_runs WHERE topic_id=? AND status IN ('dispatching','queued','running')",(topic_id,)).fetchone()
    if active:raise ServiceError(409,'该主题正在执行')
    from ..sessions.service import create_session
    from ..sessions.schemas import SessionCreate
    sid=create_session(db,SessionCreate(template_id='frontier',title=t['title']+' · '+now()))['session']['id']
    ident=uuid.uuid4().hex
    start=(datetime.now(timezone.utc)-timedelta(days=cfg['lookback_days'])).strftime('%Y-%m-%d %H:%M:%S')
    db.execute('INSERT INTO frontier_runs(id,topic_id,revision,config_json,request_key,conversation_id,window_start,window_end) VALUES (?,?,?,?,?,?,?,?)',(ident,topic_id,t['revision'],t['config_json'],key,sid,start,now()));db.commit()
    from ..agent.service import create_run
    from ..agent.schemas import RunCreate
    try:
        run=await create_run(RunCreate(conversation_id=sid,purpose='frontier',request_key='frontier:'+ident,prompt='执行当前绑定的前沿追踪任务。先调用 frontier_context，再按来源调用 frontier_search（实际结果已由平台去重），最后调用 frontier_report 保存有证据的中文简报。仅搜索与报告，不批准、不导入、不精读。'),state)
        db.execute("UPDATE frontier_runs SET agent_run_id=?,status='queued' WHERE id=?",(run['id'],ident));db.commit()
    except Exception as e:
        db.execute("UPDATE frontier_runs SET status='failed',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",(str(getattr(e,'detail',type(e).__name__))[:300],ident));db.commit();raise
    return run_view(db,require(db,'frontier_runs',ident))


def reconcile(db):
    for r in db.execute("SELECT f.*,a.status AS agent_status,a.error AS agent_error FROM frontier_runs f LEFT JOIN agent_runs a ON a.id=f.agent_run_id WHERE f.status IN ('dispatching','queued','running')").fetchall():
        status=r['agent_status']
        if status in ('queued','running'):
            db.execute('UPDATE frontier_runs SET status=? WHERE id=?',(status,r['id']));continue
        if not status:
            # A durable key permits reconciliation without resubmitting billed work.
            a=db.execute('SELECT id,status FROM agent_runs WHERE request_key=?',('frontier:'+r['id'],)).fetchone()
            if a:db.execute('UPDATE frontier_runs SET agent_run_id=?,status=? WHERE id=?',(a['id'],'queued',r['id']))
            elif r['created_at']<(datetime.now(timezone.utc)-timedelta(minutes=3)).strftime('%Y-%m-%d %H:%M:%S'):
                db.execute("UPDATE frontier_runs SET status='failed',error='分派未完成，未自动重复执行',finished_at=CURRENT_TIMESTAMP WHERE id=?",(r['id'],))
            continue
        coverage=json.loads(r['coverage_json']);cfg=json.loads(r['config_json'])
        ok={x['source'] for x in coverage if x['status']=='complete'}
        if status=='succeeded' and r['report_md']:
            final='succeeded' if set(cfg['sources'])<=ok and not any(x.get('truncated') for x in coverage) else 'partial'
            db.execute('INSERT OR IGNORE INTO frontier_reports(run_id,version,body_md,citations_json) VALUES (?,1,?,?)',(r['id'],r['report_md'],r['citations_json']))
            for c in coverage:
                if c['status']=='complete' and c.get('query_key'):
                    if c.get('next_offset') is not None:
                        db.execute('INSERT OR REPLACE INTO frontier_pages VALUES (?,?,?,?,?,?,?)',(r['topic_id'],c['source'],r['revision'],c['query_key'],c['window_start'],c['window_end'],c['next_offset']))
                    elif not c.get('truncated'):
                        db.execute('DELETE FROM frontier_pages WHERE topic_id=? AND source=? AND revision=? AND query_key=?',(r['topic_id'],c['source'],r['revision'],c['query_key']))
                source_calls=[x for x in coverage if x['source']==c['source']]
                if all(x['status']=='complete' and not x.get('truncated') for x in source_calls):
                    db.execute('INSERT OR REPLACE INTO frontier_cursors VALUES (?,?,?,?)',(r['topic_id'],c['source'],r['revision'],c.get('window_end') or r['window_end']))
            error=None
        else:
            final='output_invalid' if status=='succeeded' else status;error=r['agent_error'] or '未保存可验证报告'
        db.execute('UPDATE frontier_runs SET status=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',(final,error,r['id']))
    db.commit()


def authenticated_run(db,settings,run_id,token):
    path=Path(settings.data_dir)/'agent/internal-token'
    expected=path.read_text().strip() if path.is_file() else ''
    if not token or not expected or not hmac.compare_digest(token,expected):raise ServiceError(403,'工具未授权')
    r=db.execute('SELECT f.*,a.status AS agent_status FROM frontier_runs f JOIN agent_runs a ON a.id=f.agent_run_id WHERE f.agent_run_id=?',(run_id,)).fetchone()
    if not r or r['agent_status'] not in ('queued','running'):raise ServiceError(403,'追踪任务不存在或已经结束')
    return r


def context(db,r):
    cfg=json.loads(r['config_json']);windows={}
    for source in cfg['sources']:
        c=db.execute('SELECT watermark FROM frontier_cursors WHERE topic_id=? AND source=? AND revision=?',(r['topic_id'],source,r['revision'])).fetchone()
        start=r['window_start']
        if c:start=(datetime.fromisoformat(c[0])-timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        windows[source]={'start':start,'end':r['window_end']}
    return {'topic_id':r['topic_id'],'config':cfg,'windows':windows,'run_id':r['id'],'timezone':'UTC','warning':'作者/团队是软匹配提示；不要宣称精确实体过滤。范围或分页截断需要在报告中说明。'}


def ingest(db,r,source,query,result=None,error=None):
    sync_existing_library(db)
    cfg=json.loads(r['config_json'])
    if source not in cfg['sources']:raise ServiceError(400,'来源不在本轮配置内')
    evidence=[];result=result or {};records=result.get('records',[])[:cfg['max_results']]
    try:
        for m in records:
            if not m.get('title'):continue
            keys=identity.identifiers(m)
            matches={x[0] for k in keys for x in db.execute('SELECT entity_id FROM frontier_aliases WHERE alias=?',(k,))}
            if len(matches)>1:raise ServiceError(409,'身份交叉冲突，需要人工核验')
            e=db.execute('SELECT * FROM frontier_entities WHERE id=?',(next(iter(matches)),)).fetchone() if matches else None
            paper=identity.find_paper(db,m) if m['kind']=='paper' else None
            project=db.execute('SELECT id FROM projects WHERE repo_key=?',(next((k for k in keys if k.startswith('repo:')),''),)).fetchone() if m['kind']=='project' else None
            if e and m['kind']=='project' and not m.get('release_checked'):
                m['release']=json.loads(e['metadata_json']).get('release')
            hash_=identity.fingerprint(m)
            if e:
                ident=e['id'];change='in_library' if json.loads(e['metadata_json']).get('evidence_level')=='library_baseline' else ('updated' if hash_!=e['content_hash'] else 'known')
                if hash_!=e['content_hash']:db.execute('UPDATE frontier_items SET revision=revision+1 WHERE entity_id=?',(ident,))
                db.execute('UPDATE frontier_entities SET metadata_json=?,content_hash=?,paper_id=coalesce(?,paper_id),project_id=coalesce(?,project_id),last_seen=CURRENT_TIMESTAMP WHERE id=?',(dump(m),hash_,paper,project[0] if project else None,ident))
            else:
                change='in_library' if paper or project else 'new'
                ident=db.execute('INSERT INTO frontier_entities(kind,canonical_key,metadata_json,content_hash,paper_id,project_id) VALUES (?,?,?,?,?,?)',(m['kind'],keys[0],dump(m),hash_,paper,project[0] if project else None)).lastrowid
            for key in keys:db.execute('INSERT OR IGNORE INTO frontier_aliases VALUES (?,?)',(key,ident))
            db.execute('INSERT INTO frontier_items(topic_id,entity_id) VALUES (?,?) ON CONFLICT(topic_id,entity_id) DO UPDATE SET last_seen=CURRENT_TIMESTAMP',(r['topic_id'],ident))
            old=db.execute('SELECT id,change_type FROM frontier_evidence WHERE run_id=? AND entity_id=? AND content_hash=?',(r['id'],ident,hash_)).fetchone()
            eid=old[0] if old else uuid.uuid4().hex
            if old:change=old['change_type']
            if not old:db.execute('INSERT INTO frontier_evidence(id,run_id,entity_id,snapshot_json,content_hash,change_type,source,query) VALUES (?,?,?,?,?,?,?,?)',(eid,r['id'],ident,dump(m),hash_,change,source,query))
            evidence.append({'evidence_id':eid,'entity_id':ident,'change_type':change,'paper_id':paper,'metadata':m})
        coverage=json.loads(require(db,'frontier_runs',r['id'])['coverage_json'])
        coverage.append({'source':source,'query':query,'status':'failed' if error else 'complete','error':error,'retrieved':len(records),'total':result.get('total',0),'truncated':result.get('truncated',False),'window_start':result.get('window_start'),'window_end':result.get('window_end'),'next_offset':result.get('next_offset'),'query_key':result.get('query_key')})
        db.execute('UPDATE frontier_runs SET coverage_json=? WHERE id=?',(dump(coverage),r['id']));db.commit()
    except Exception:db.rollback();raise
    return {'items':evidence,'coverage':coverage[-1]}


def save_report(db,r,body:Report):
    valid={x[0] for x in db.execute('SELECT id,change_type FROM frontier_evidence WHERE run_id=?',(r['id'],))}
    if not set(body.citations)<=valid or not set(body.reasons)<=valid or not set(re.findall(r'\[证据[:：]([^\]]+)\]',body.markdown))<=valid:raise ServiceError(400,'报告引用不属于本轮真实工具证据')
    if valid and not body.citations:raise ServiceError(400,'有发现内容时报告必须包含证据引用')
    if not json.loads(require(db,'frontier_runs',r['id'])['coverage_json']):raise ServiceError(400,'必须先执行真实检索')
    for eid,reason in body.reasons.items():db.execute('UPDATE frontier_evidence SET reason=? WHERE id=?',(reason[:1200],eid))
    db.execute('UPDATE frontier_runs SET report_md=?,citations_json=? WHERE id=?',(body.markdown,dump(body.citations),r['id']));db.commit()
    return {'saved':True,'evidence_ids':body.citations,'warning':'报告在 Agent 运行成功结束后发布；候选未获入库批准'}


def refresh_library_link(db,e):
    if e['kind']=='paper' and not e['paper_id']:
        pid=identity.find_paper(db,json.loads(e['metadata_json']))
        if pid:db.execute('UPDATE frontier_entities SET paper_id=? WHERE id=?',(pid,e['id']));return pid,e['project_id']
    return e['paper_id'],e['project_id']


def item_view(db,r):
    d=dict(r);d['metadata']=json.loads(d.pop('metadata_json'))
    d['paper_id'],d['project_id']=refresh_library_link(db,r)
    d['in_library']=bool(d['paper_id'] or d['project_id'])
    d['similar_paper_ids']=identity.similar_papers(db,d['metadata']) if d['kind']=='paper' and not d['in_library'] else []
    return d


def items(db,topic_id=None,before=None,limit=200):
    clauses=[];params=[]
    if topic_id:clauses.append('i.topic_id=?');params.append(topic_id)
    if before:
        eid,tid=map(int,before.split(':'));clauses.append('(e.id<? OR (e.id=? AND i.topic_id<?))');params.extend([eid,eid,tid])
    where='WHERE '+' AND '.join(clauses) if clauses else '';params.append(limit)
    rows=db.execute(f'SELECT e.*,i.topic_id,i.decision,i.revision,i.approved_hash FROM frontier_items i JOIN frontier_entities e ON e.id=i.entity_id {where} ORDER BY e.id DESC,i.topic_id DESC LIMIT ?',params).fetchall()
    out=[item_view(db,r) for r in rows];db.commit();return out


def run_view(db,r):
    d=dict(r);d['config']=json.loads(d.pop('config_json'));d['coverage']=json.loads(d.pop('coverage_json'));d['citations']=json.loads(d.pop('citations_json'))
    evid=[]
    for x in db.execute('SELECT v.*,e.paper_id,e.project_id,i.decision,i.revision FROM frontier_evidence v JOIN frontier_entities e ON e.id=v.entity_id JOIN frontier_items i ON i.entity_id=e.id AND i.topic_id=? WHERE v.run_id=? ORDER BY v.created_at,v.id',(r['topic_id'],r['id'])):
        q=dict(x);q['metadata']=json.loads(q.pop('snapshot_json'));e=require(db,'frontier_entities',x['entity_id']);q['paper_id'],q['project_id']=refresh_library_link(db,e);q['in_library']=bool(q['paper_id'] or q['project_id']);evid.append(q)
    d['items']=evid;d['counts']={k:sum(x['change_type']==k for x in evid) for k in ('new','updated','known','in_library')}
    a=db.execute('SELECT usage_json,cli_estimated_cost_usd FROM agent_runs WHERE id=?',(r['agent_run_id'],)).fetchone()
    d['usage']=json.loads(a[0]) if a else {};d['cost']=a[1] if a else None
    return d


async def decide(db,state,topic_id,entity_id,body):
    data=dump(body.model_dump(exclude={'request_key'}));prior=db.execute('SELECT * FROM frontier_decisions WHERE request_key=?',(body.request_key,)).fetchone()
    if prior:
        if prior['topic_id']!=topic_id or prior['entity_id']!=entity_id or prior['body_json']!=data:raise ServiceError(409,'请求编号已用于其他操作')
        return json.loads(prior['result_json'])
    validate_collections(db,body.collection_ids)
    try:
        db.execute('BEGIN IMMEDIATE')
        e=require(db,'frontier_entities',entity_id);i=db.execute('SELECT * FROM frontier_items WHERE topic_id=? AND entity_id=?',(topic_id,entity_id)).fetchone()
        if not i:raise ServiceError(404,'候选不存在')
        if i['revision']!=body.revision:raise ServiceError(409,'候选已变化，请刷新')
        pid,project=refresh_library_link(db,e);m=json.loads(e['metadata_json'])
        if body.action=='approve':
            if not pid and not project:
                if e['kind']=='paper':
                    if identity.similar_papers(db,m) and not body.confirm_distinct:raise ServiceError(409,'题名与已有论文相同，请先核验身份或确认独立资料')
                    keys=identity.identifiers(m)
                    arxiv=next((k[6:] for k in keys if k.startswith('arxiv:')),None);doi=next((k[4:] for k in keys if k.startswith('doi:')),None)
                    pid=db.execute("INSERT INTO papers(title,authors,abstract,source,arxiv_id,doi,source_url,affiliations,frontier_entity_id) VALUES (?,?,?,'import',?,?,?,?,?)",(m['title'],dump(m.get('authors',[])),m.get('abstract',''),arxiv,doi,m.get('url'),dump(m.get('affiliations',[])),entity_id)).lastrowid
                else:
                    key=next(k for k in identity.identifiers(m) if k.startswith('repo:'))
                    project=db.execute('INSERT INTO projects(repo_key,title,url,description,owner,license,metadata_json) VALUES (?,?,?,?,?,?,?)',(key,m['title'],m['url'],m.get('description',''),m.get('owner',''),m.get('license'),dump(m))).lastrowid
                db.execute('UPDATE frontier_entities SET paper_id=?,project_id=? WHERE id=?',(pid,project,entity_id))
            for cid in body.collection_ids:
                if pid:db.execute('INSERT OR IGNORE INTO paper_collection_items VALUES (?,?)',(cid,pid))
                if project:db.execute('INSERT OR IGNORE INTO project_collection_items VALUES (?,?)',(project,cid))
            # Global admission is reflected by entity link; topical decisions stay independent.
            decision='approved'
        else:decision='ignored' if body.action=='ignore' else 'pending'
        db.execute('UPDATE frontier_items SET decision=?,revision=revision+1,approved_hash=? WHERE topic_id=? AND entity_id=?',(decision,e['content_hash'] if body.action=='approve' else i['approved_hash'],topic_id,entity_id))
        out={'saved':True,'paper_id':pid,'project_id':project,'decision':decision}
        db.execute('INSERT INTO frontier_decisions(request_key,topic_id,entity_id,action,body_json,result_json) VALUES (?,?,?,?,?,?)',(body.request_key,topic_id,entity_id,body.action,data,dump(out)));db.commit()
    except Exception:db.rollback();raise
    if body.fulltext and pid and body.action=='approve':
        from ..imports.service import submit_source
        from ..imports.schemas import Source
        try:out['import']=await submit_source(db,Source(value=m.get('doi') or m.get('url',''),target_paper_id=pid,request_key='frontier-import:'+body.request_key),state)
        except ServiceError as exc:out['import_error']=str(exc.detail)
        db.execute('UPDATE frontier_decisions SET result_json=? WHERE request_key=?',(dump(out),body.request_key));db.commit()
    return out
