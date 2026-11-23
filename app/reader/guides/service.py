"""Explicit trigger, evidence validation and projection onto existing annotations."""
import hashlib,hmac,json,uuid
from pathlib import Path
from ...core.errors import ServiceError
from .. import pages,repository as annotations_repo,service as reader_service
from ..schemas import Annotation
from . import materials
from .schemas import GuideCreate,GuideResult

ACTIVE=('dispatching','queued','running','staging')
TERMINAL=('published','partial','failed','cancelled','rejected','stale')
def dump(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
def task(db,ident):
    r=db.execute('SELECT * FROM reader_guide_tasks WHERE id=?',(ident,)).fetchone()
    if not r:raise ServiceError(404,'导读任务不存在')
    return r

def policy(db,skill_id,version_id=None):
    from ...skills.service import ensure_builtin_skills,execution_policy
    ensure_builtin_skills(db)
    if version_id and not db.execute('SELECT 1 FROM skill_versions WHERE id=? AND skill_id=?',(version_id,skill_id)).fetchone():raise ServiceError(400,'技能版本与技能不匹配')
    try:p=execution_policy(db,skill_id,version_id)
    except ValueError as e:raise ServiceError(409,str(e)) from e
    required={'reader_guide_context','reader_guide_material','reader_guide_submit'}
    if not required<=set(p['tools']) or p['max_calls']<3 or p['max_output_tokens']<4096:raise ServiceError(409,'此技能尚未通过导读工具和输出额度兼容检查')
    return p

async def create(db,state,pid,body:GuideCreate):
    from ...skills.authoring import placements
    from ...skills.service import ensure_builtin_skills
    ensure_builtin_skills(db)
    if 'guide' not in placements(db,body.skill_id)['surfaces']:raise ServiceError(409,'技能未开放到导读批注')
    paper=reader_service.paper(db,pid)
    try:info=pages.document_info(state.settings,paper)
    except (ValueError,OSError) as e:raise ServiceError(400,str(e)) from e
    if info['file_version']!=body.file_version:raise ServiceError(409,'PDF 版本已变化，请刷新后再触发')
    reconcile(db,state.settings,pid)
    p=policy(db,body.skill_id,body.skill_version_id)
    cfg=body.model_dump(exclude={'request_key','confirmed','file_version','skill_version_id'})
    key=hashlib.sha256(dump([pid,body.file_version,p['version_id'],p['skill_hash'],'paper-guide/v1',cfg]).encode()).hexdigest()
    prior=db.execute('SELECT * FROM reader_guide_tasks WHERE request_key=?',(body.request_key,)).fetchone()
    if prior:
        if prior['semantic_key']!=key:raise ServiceError(409,'请求编号已用于其他导读参数')
        return view(db,prior,cached=True)
    existing=db.execute("SELECT * FROM reader_guide_tasks WHERE semantic_key=? AND hidden=0 AND status IN ('dispatching','queued','running','staging','published','partial')",(key,)).fetchone()
    if existing:return view(db,existing,cached=True)
    from ...agent.service import status_view,create_run
    from ...agent.schemas import RunCreate
    health=await status_view(db)
    if not health['runner_protocol_compatible']:raise ServiceError(409,'智能体离线或版本不匹配，请先同步 Runner')
    # Recheck after the only network await: simultaneous tabs must share a run.
    existing=db.execute("SELECT * FROM reader_guide_tasks WHERE semantic_key=? AND hidden=0 AND status IN ('dispatching','queued','running','staging','published','partial')",(key,)).fetchone()
    if existing:return view(db,existing,cached=True)
    from ...sessions.service import create_session
    from ...sessions.schemas import SessionCreate
    template='guide_'+hashlib.sha256(body.skill_id.encode()).hexdigest()[:16]
    db.execute("INSERT OR IGNORE INTO task_templates(id,name,description,kind,skill,prompt,builtin) VALUES (?,?,?,?,?,'',0)",(template,'论文导读与批注','用户触发的结构化导读','reading',body.skill_id));db.commit()
    sid=create_session(db,SessionCreate(template_id=template,paper_ids=[pid],title=(paper['title'] or '论文')[:80]+' · 导读批注'))['session']['id']
    db.execute('UPDATE conversations SET skill_version_id=? WHERE id=?',(p['version_id'],sid))
    ident=uuid.uuid4().hex
    db.execute('INSERT INTO reader_guide_tasks(id,paper_id,file_version,semantic_key,request_key,request_json,skill_id,skill_version_id,skill_hash,conversation_id,manifest_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,pid,body.file_version,key,body.request_key,dump(cfg),body.skill_id,p['version_id'],p['skill_hash'],sid,uuid.uuid4().hex));db.commit()
    try:
        run=await create_run(RunCreate(conversation_id=sid,purpose='guide',request_key='guide:'+ident,prompt='用户已明确触发论文导读和批注。先 reader_guide_context，再 reader_guide_material 获取有界真实原文，最后 reader_guide_submit 输出 paper-guide/v1。解释为什么重要并保留证据块，不能猜坐标。不要等待站间确认，不修改人工批注。'),state)
        db.execute("UPDATE reader_guide_tasks SET agent_run_id=?,status='queued' WHERE id=?",(run['id'],ident));db.commit()
    except Exception as e:
        db.execute("UPDATE reader_guide_tasks SET status='failed',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",(str(getattr(e,'detail',type(e).__name__))[:300],ident));db.commit();raise
    return view(db,task(db,ident),cached=False)


def authorized(db,settings,run_id,token):
    path=Path(settings.data_dir)/'agent/internal-token'
    expected=path.read_text().strip() if path.is_file() else ''
    if not token or not expected or not hmac.compare_digest(token,expected):raise ServiceError(403,'工具未授权')
    r=db.execute('SELECT t.*,a.status AS agent_status,a.skill AS agent_skill FROM reader_guide_tasks t JOIN agent_runs a ON a.id=t.agent_run_id WHERE t.agent_run_id=?',(run_id,)).fetchone()
    if not r or r['agent_status'] not in ('queued','running') or r['status'] not in ACTIVE or r['agent_skill']!=r['skill_id']:raise ServiceError(403,'导读任务未绑定或已结束')
    _,version=pages.pdf_file(settings,reader_service.paper(db,r['paper_id']))
    if version!=r['file_version']:raise ServiceError(409,'PDF 文件版本已变化')
    return r


def context(db,settings,r):
    info=pages.document_info(settings,reader_service.paper(db,r['paper_id']))
    return {'task_id':r['id'],'paper_id':r['paper_id'],'file_version':r['file_version'],'material_manifest_id':r['manifest_id'],'config':json.loads(r['request_json']),'document':{k:info[k] for k in ('title','page_count','outline')},'output_contract':'paper-guide/v1','capabilities':{'text':True,'figures':False,'vision':False,'code_read':False},'instructions':'只可引用 reader_guide_material 返回的 block_id、material_id 和原文。当前仅文本能力，不能声称看图或读代码。'}


def material(db,settings,r,selected):
    cfg=json.loads(r['request_json']);selected=list(dict.fromkeys(selected))
    existing=[dict(x) for x in db.execute('SELECT * FROM reader_guide_blocks WHERE task_id=?',(r['id'],))]
    coverage=json.loads(r['coverage_json']);old_pages=coverage.get('provided_pages',[])
    if len(set(old_pages+selected))>cfg['max_pages']:raise ServiceError(400,'本轮材料页数超出用户选择的上限')
    new=[n for n in selected if n not in old_pages]
    if new:
        extracted=materials.extract(settings,reader_service.paper(db,r['paper_id']),r['id'],new)
        if extracted['file_version']!=r['file_version']:raise ServiceError(409,'材料版本已变化')
        if sum(len(x['text']) for x in existing)+sum(len(x['text']) for x in extracted['blocks'])>materials.MAX_CHARS:raise ServiceError(400,'本轮材料已达字符上限，请使用已有材料')
        for b in extracted['blocks']:db.execute('INSERT OR IGNORE INTO reader_guide_blocks VALUES (?,?,?,?,?,?)',(b['id'],r['id'],b['material_id'],b['page'],b['text'],dump(b['data'])))
        coverage={'provided_pages':sorted(set(old_pages+extracted['provided_pages'])),'truncated':bool(coverage.get('truncated') or extracted['truncated']),'figures_read':False,'code_read':False}
        db.execute('UPDATE reader_guide_tasks SET coverage_json=? WHERE id=?',(dump(coverage),r['id']));db.commit()
    records=[{'block_id':x['id'],'material_id':x['material_id'],'page':x['page'],'text':x['text']} for x in db.execute('SELECT * FROM reader_guide_blocks WHERE task_id=? ORDER BY page,id',(r['id'],))]
    if not records:raise ServiceError(400,'所选页没有可抽取的文本，当前 Skill 不具备 OCR/视觉能力')
    return {'material_manifest_id':r['manifest_id'],'blocks':records,'coverage':coverage,'material_ids':list(dict.fromkeys(x['material_id'] for x in records))}


def submit(db,settings,r,body:GuideResult):
    if body.material_manifest_id!=r['manifest_id']:raise ServiceError(409,'材料清单未绑定到本次任务')
    blocks={x['id']:x for x in db.execute('SELECT * FROM reader_guide_blocks WHERE task_id=?',(r['id'],))}
    actual=json.loads(task(db,r['id'])['coverage_json']);cfg=json.loads(r['request_json'])
    if not blocks:raise ServiceError(422,'请先读取实际材料')
    if len(body.items)>cfg['max_items']:raise ServiceError(422,'批注数量超出用户选择的上限')
    if body.coverage.figures_read or body.coverage.code_read:raise ServiceError(422,'当前没有读图或代码工具证据')
    if not set(body.coverage.material_ids)<={b['material_id'] for b in blocks.values()}:raise ServiceError(422,'覆盖声明引用未知材料')
    info=pages.document_info(settings,reader_service.paper(db,r['paper_id']))
    if body.coverage.scope=='fulltext' and (actual.get('truncated') or len(actual.get('provided_pages',[]))!=info['page_count']):raise ServiceError(422,'不能将部分材料声明为全文覆盖')
    keys=[i.key for i in body.items]
    if len(keys)!=len(set(keys)):raise ServiceError(422,'重点 key 重复')
    for route in body.reading_route:
        if not set(route.item_keys)<=set(keys) or not set(route.block_ids)<=blocks.keys():raise ServiceError(422,'阅读路线包含未知重点或证据块')
    resolved=[];warnings=[]
    for item in body.items:
        anchors=[]
        for a in item.anchors:
            if a.type=='asset':raise ServiceError(422,'当前材料没有可用的图表资产锚点')
            if a.block_id not in blocks:raise ServiceError(422,'批注引用了未提供或不属于本轮的证据块')
            located=materials.locate(blocks[a.block_id],a);anchors.append(located)
            if located['status']!='verified':warnings.append({'item_key':item.key,'status':located['status'],'page':located['page']})
        resolved.append({'item':item.model_dump(),'anchors':anchors})
    payload=body.model_dump();payload['_resolved']=resolved
    current=task(db,r['id'])
    serialized=dump(payload)
    if current['payload_json'] and current['payload_json']!=serialized:raise ServiceError(409,'本轮已提交不同结果；请新建显式任务以重新生成')
    db.execute("UPDATE reader_guide_tasks SET payload_json=?,validation_json=?,status='staging' WHERE id=?",(serialized,dump(warnings),r['id']));db.commit()
    return {'staged':True,'items':len(resolved),'warnings':warnings,'message':'执行成功后再发布；不修改人工批注，无法唯一定位的内容只显示页级笔记。'}


def location_status(anchors):
    verified=sum(a['status']=='verified' for a in anchors)
    return 'verified' if verified==len(anchors) and verified else 'mixed' if verified else 'page_only'


def publish(db,settings,r):
    paper=reader_service.paper(db,r['paper_id']);info=pages.document_info(settings,paper)
    if info['file_version']!=r['file_version']:raise ServiceError(409,'文件版本已变化，旧结果不激活')
    data=json.loads(r['payload_json']);coverage=json.loads(r['coverage_json']);warnings=json.loads(r['validation_json'])
    partial=bool(warnings or coverage.get('truncated') or len(coverage.get('provided_pages',[]))<info['page_count'] or not data['items'])
    db.execute('UPDATE reader_guide_tasks SET active=0 WHERE paper_id=?',(r['paper_id'],))
    for resolved in data['_resolved']:
        item=resolved['item'];anchors=resolved['anchors'];iid=uuid.uuid4().hex
        location=location_status(anchors)
        db.execute('INSERT INTO reader_guide_items VALUES (?,?,?,?,?,?)',(iid,r['id'],item['key'],dump(item),dump(anchors),location))
        content=(f"### {item['title']}\n\n**为什么重要**\n\n{item['why_important_md']}\n\n**解释**\n\n{item['explanation_md']}")[:7800]
        for a in anchors:
            rects=a['rects'] if a['status']=='verified' else []
            body=Annotation(paper_id=r['paper_id'],file_version=r['file_version'],page=a['page'],quote=a['quote'] if rects else '',rects=rects,kind='highlight' if rects else 'note',content=content,color='#f4b6d5' if item['category']=='limitation' else '#9ed8ff',conversation_id=r['conversation_id'])
            aid=reader_service.insert_annotation_record(db,body)
            db.execute("UPDATE reader_annotations SET origin='ai',guide_task_id=?,guide_item_id=? WHERE id=?",(r['id'],iid,aid))
    db.execute('UPDATE reader_guide_tasks SET status=?,active=1,finished_at=CURRENT_TIMESTAMP WHERE id=?',('partial' if partial else 'published',r['id']))


def reconcile(db,settings,pid=None):
    where=' AND t.paper_id=?' if pid else '';args=(pid,) if pid else ()
    rows=db.execute("SELECT t.*,a.status AS agent_status,a.error AS agent_error FROM reader_guide_tasks t LEFT JOIN agent_runs a ON a.id=t.agent_run_id WHERE t.status IN ('dispatching','queued','running','staging')"+where,args).fetchall()
    for r in rows:
        status=r['agent_status']
        if status in ('queued','running'):
            if r['status']!='staging':db.execute('UPDATE reader_guide_tasks SET status=? WHERE id=?',(status,r['id']))
            continue
        if not status:
            orphan=db.execute('SELECT id FROM agent_runs WHERE request_key=?',('guide:'+r['id'],)).fetchone()
            if orphan:db.execute('UPDATE reader_guide_tasks SET agent_run_id=? WHERE id=?',(orphan[0],r['id']))
            elif db.execute("SELECT created_at<datetime('now','-3 minutes') FROM reader_guide_tasks WHERE id=?",(r['id'],)).fetchone()[0]:db.execute("UPDATE reader_guide_tasks SET status='failed',error='分派中断，未自动重新执行' WHERE id=?",(r['id'],))
            continue
        if status=='succeeded' and r['payload_json']:
            try:publish(db,settings,r);db.commit()
            except Exception as exc:
                db.rollback();db.execute("UPDATE reader_guide_tasks SET status='rejected',error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",(str(getattr(exc,'detail','发布校验失败'))[:400],r['id']))
        else:db.execute('UPDATE reader_guide_tasks SET status=?,error=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',('rejected' if status=='succeeded' else status,r['agent_error'] or 'Skill 未提交可验证的结构化导读',r['id']))
    db.commit()


def view(db,r,cached=False):
    d={k:r[k] for k in ('id','paper_id','file_version','skill_id','skill_version_id','conversation_id','agent_run_id','status','active','hidden','error','created_at','finished_at')}
    d['cached']=cached;d['coverage']=json.loads(r['coverage_json']);d['warnings']=json.loads(r['validation_json'])
    payload=json.loads(r['payload_json']) if r['payload_json'] and r['status'] in ('published','partial','stale') else None
    if payload:payload.pop('_resolved',None)
    d['result']=payload;d['items']=[]
    if payload:
        for row in db.execute('SELECT * FROM reader_guide_items WHERE task_id=? ORDER BY rowid',(r['id'],)):
            anns=[dict(a) for a in db.execute('SELECT id,page,deleted,kind FROM reader_annotations WHERE guide_item_id=? AND origin=?',(row['id'],'ai'))]
            d['items'].append({'id':row['id'],'item':json.loads(row['item_json']),'anchors':json.loads(row['anchors_json']),'location_status':location_status(json.loads(row['anchors_json'])),'annotations':anns})
    a=db.execute('SELECT usage_json,cli_estimated_cost_usd FROM agent_runs WHERE id=?',(r['agent_run_id'],)).fetchone()
    d['usage']=json.loads(a[0]) if a else {};d['cost']=a[1] if a else None
    return d


def current(db,settings,pid):
    paper=reader_service.paper(db,pid);reconcile(db,settings,pid)
    _,version=pages.pdf_file(settings,paper)
    rows=db.execute('SELECT * FROM reader_guide_tasks WHERE paper_id=? AND hidden=0 ORDER BY rowid DESC',(pid,)).fetchall()
    latest=next((r for r in rows if r['file_version']==version),None)
    active=next((r for r in rows if r['file_version']==version and r['active']),None)
    return {'task':view(db,latest) if latest else None,'guide':view(db,active) if active else None,'older_versions':sum(r['file_version']!=version for r in rows)}
