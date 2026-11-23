"""Immutable research assets and reviewed account-private knowledge."""
import hashlib
import json
import re
import uuid
from ..core.errors import ServiceError
from ..documents import service as documents
from ..reader import pages
from .schemas import ArtifactWrite,KnowledgeWrite
from . import materials

def dump(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)
def audit(db,kind,ident,action,revision):db.execute('INSERT INTO research_audit(resource_type,resource_id,action,revision) VALUES (?,?,?,?)',(kind,ident,action,revision))
def require(db,table,ident):
    if table not in ('research_artifacts','knowledge_items'):raise ValueError('Invalid resource')
    r=db.execute(f'SELECT * FROM {table} WHERE id=?',(ident,)).fetchone()
    if not r:raise ServiceError(404,'记录不存在')
    return r

def paper_ids(db,artifact_id):return [r[0] for r in db.execute('SELECT paper_id FROM artifact_papers WHERE artifact_id=? ORDER BY paper_id',(artifact_id,))]

def check_papers(db,ids):
    if len(set(ids))!=len(ids):raise ServiceError(422,'论文关联不能重复')
    for pid in ids:
        if not db.execute('SELECT 1 FROM papers WHERE id=? AND deleted_at IS NULL',(pid,)).fetchone():raise ServiceError(404,'论文不存在或已删除')

def validate_evidence(db,settings,entries,ids):
    evidence=[]
    for e in entries:
        if e.paper_id not in ids:raise ServiceError(422,'引用论文必须关联到产物')
        version=documents.version(db,e.paper_id,e.document_version_id)
        if version['file_hash']!=e.file_version:raise ServiceError(409,'引用文件版本不匹配')
        paper=dict(db.execute('SELECT * FROM papers WHERE id=?',(e.paper_id,)).fetchone())
        paper['pdf_path']=str(documents.asset_path(settings,version['storage_key']))
        try:content=pages.read_page(settings,paper,e.page)
        except (ValueError,OSError):raise ServiceError(422,'引用页不可读取') from None
        norm=lambda s:re.sub(r'\s+','',s).casefold()
        if e.quote and norm(e.quote) not in norm(content['text']):raise ServiceError(409,'引文未在指定原文页找到')
        evidence.append(e.model_dump()|{'verification':'quote_verified' if e.quote else 'page_verified'})
    return evidence

def artifact_view(db,ident,revision=None):
    row=require(db,'research_artifacts',ident);rev=revision or row['current_revision']
    r=db.execute('SELECT * FROM artifact_revisions WHERE artifact_id=? AND revision=?',(ident,rev)).fetchone()
    if not r:raise ServiceError(404,'产物修订不存在')
    return dict(row)|{'revision':rev,'markdown':r['markdown'],'status':r['status'],'paper_ids':paper_ids(db,ident),'evidence':json.loads(r['evidence_json']),'materials':json.loads(r['materials_json']),'files':[dict(f) for f in db.execute('SELECT f.* FROM artifact_files a JOIN research_files f ON f.hash=a.file_hash WHERE a.artifact_id=? AND a.revision=?',(ident,rev))],'producer':json.loads(r['producer_json']),'revisions':[x[0] for x in db.execute('SELECT revision FROM artifact_revisions WHERE artifact_id=? ORDER BY revision DESC',(ident,))]}

def artifact_save(db,settings,body,ident=None,origin='web',source_key=None,checked=False):
    if not body.title.strip() or not body.markdown.strip():raise ServiceError(422,'名称与内容不能为空')
    ids=sorted(body.paper_ids);check_papers(db,ids)
    evidence=validate_evidence(db,settings,body.evidence,ids)
    for fid in body.file_ids:
        f=db.execute('SELECT paper_id FROM research_files WHERE hash=?',(fid,)).fetchone()
        if not f or f[0] not in ids:raise ServiceError(404,'附件不存在或不属于关联论文')
    frozen={}
    if body.source_run_id:
        r=db.execute('SELECT * FROM agent_runs WHERE id=?',(body.source_run_id,)).fetchone()
        if not r:raise ServiceError(404,'来源任务不存在')
        linked={x[0] for x in db.execute('SELECT paper_id FROM conversation_papers WHERE conversation_id=?',(r['conversation_id'],))}
        if set(ids)!=linked:raise ServiceError(422,'产物论文不属于来源任务')
        frozen=materials.frozen(db,body.source_run_id)
    if ident:
        current=require(db,'research_artifacts',ident)
        if body.expected_revision!=current['current_revision']:raise ServiceError(409,'产物已更新，请刷新')
        if ids!=paper_ids(db,ident) or body.source_run_id!=current['source_run_id']:raise ServiceError(409,'修订不能改变来源与论文范围，请新建产物')
        revision=current['current_revision']+1
        changed=db.execute('UPDATE research_artifacts SET title=?,kind=?,current_revision=? WHERE id=? AND current_revision=?',(body.title.strip(),body.kind,revision,ident,body.expected_revision))
        if not changed.rowcount:raise ServiceError(409,'产物修订冲突')
        affected=[r[0] for r in db.execute('SELECT knowledge_id FROM knowledge_sources WHERE artifact_id=?',(ident,))]
        for kid in affected:
            db.execute('UPDATE knowledge_items SET needs_review=1 WHERE id=?',(kid,));db.execute('DELETE FROM knowledge_fts WHERE id=?',(kid,))
    else:
        ident=uuid.uuid4().hex;revision=1
        db.execute('INSERT INTO research_artifacts(id,title,kind,current_revision,source_key,source_run_id,origin) VALUES (?,?,?,?,?,?,?)',(ident,body.title.strip(),body.kind,revision,source_key,body.source_run_id,origin))
        db.executemany('INSERT INTO artifact_papers VALUES (?,?)',[(ident,pid) for pid in ids])
    producer={'name':body.producer,'origin':origin,'content_claim':'producer_supplied','evidence_checked':True}
    db.execute('INSERT INTO artifact_revisions(artifact_id,revision,markdown,evidence_json,materials_json,status,producer_json) VALUES (?,?,?,?,?,?,?)',(ident,revision,body.markdown,dump(evidence),dump(frozen),body.status,dump(producer)))
    db.executemany('INSERT INTO artifact_files VALUES (?,?,?)',[(ident,revision,fid) for fid in set(body.file_ids)])
    audit(db,'artifact',ident,'revise' if revision>1 else 'create',revision)
    return artifact_view(db,ident)

def capture_run(db,settings,run_id):
    source='run:'+run_id
    if db.execute('SELECT 1 FROM research_artifacts WHERE source_key=?',(source,)).fetchone():return
    r=db.execute('SELECT * FROM agent_runs WHERE id=?',(run_id,)).fetchone()
    if not r or not r['answer']:return
    ids=[x[0] for x in db.execute('SELECT paper_id FROM conversation_papers WHERE conversation_id=?',(r['conversation_id'],))]
    skill=r['skill'];kind='comparison' if skill=='paper_compare' else 'review' if skill=='paper_review' else 'reading'
    if r['purpose'] in ('translate','explain','guide','skill-validation'):kind='note'
    body=ArtifactWrite(title=r['prompt'][:160],kind=kind,markdown=r['answer'][:100000],paper_ids=ids,status='complete' if r['status']=='succeeded' and len(r['answer'])<=100000 else 'partial',source_run_id=run_id,producer=skill+':'+str(r['skill_version_id'] or 'unknown'))
    return artifact_save(db,settings,body,origin='agent',source_key=source)

def artifact_list(db,q='',pid=None,before=None,limit=30,allowed=None):
    clauses=['a.archived=0','NOT EXISTS(SELECT 1 FROM artifact_papers ap JOIN papers p ON p.id=ap.paper_id WHERE ap.artifact_id=a.id AND p.deleted_at IS NOT NULL)'];args=[]
    if q:clauses.append('instr(lower(a.title),lower(?))>0');args.append(q)
    if pid is not None:clauses.append('EXISTS(SELECT 1 FROM artifact_papers p WHERE p.artifact_id=a.id AND p.paper_id=?)');args.append(pid)
    if before:clauses.append('a.rowid<?');args.append(before)
    if allowed is not None:
        marks=','.join('?' for _ in allowed)
        clauses+=['EXISTS(SELECT 1 FROM artifact_papers p WHERE p.artifact_id=a.id)',f'NOT EXISTS(SELECT 1 FROM artifact_papers p WHERE p.artifact_id=a.id AND p.paper_id NOT IN ({marks}))'];args+=allowed
    rows=db.execute('SELECT a.*,a.rowid AS cursor FROM research_artifacts a WHERE '+' AND '.join(clauses)+' ORDER BY a.rowid DESC LIMIT ?',args+[limit+1]).fetchall()
    items=[artifact_view(db,r['id'])|{'cursor':r['cursor']} for r in rows[:limit]]
    return {'artifacts':items,'has_more':len(rows)>limit,'next_before':items[-1]['cursor'] if items else None}

def source_views(db,sources,require_current=False):
    out=[]
    for ref in sources:
        a=artifact_view(db,ref.artifact_id,ref.revision)
        if a['archived'] or a['status'] in ('failed','draft'):raise ServiceError(409,'不能引用未完成或已归档产物')
        check_papers(db,a['paper_ids'])
        if require_current and a['current_revision']!=ref.revision:raise ServiceError(409,'来源已更新，请重新审核最新修订')
        out.append(a)
    if len({r.artifact_id for r in sources})!=len(sources):raise ServiceError(422,'来源不能重复')
    return out

def knowledge_view(db,ident,revision=None):
    row=require(db,'knowledge_items',ident);rev=revision or row['current_revision']
    r=db.execute('SELECT * FROM knowledge_revisions WHERE knowledge_id=? AND revision=?',(ident,rev)).fetchone()
    if not r:raise ServiceError(404,'知识修订不存在')
    refs=json.loads(r['sources_json']);sources=[]
    for ref in refs:
        a=artifact_view(db,ref['artifact_id'],ref['revision'])
        sources.append({'artifact_id':a['id'],'revision':a['revision'],'current_revision':a['current_revision'],'title':a['title'],'paper_ids':a['paper_ids'],'evidence':a['evidence'],'archived':bool(a['archived'])})
    return dict(row)|{'revision':rev,'markdown':r['markdown'],'claim_type':r['claim_type'],'sources':sources,'revisions':[x[0] for x in db.execute('SELECT revision FROM knowledge_revisions WHERE knowledge_id=? ORDER BY revision DESC',(ident,))]}

def knowledge_save(db,body,ident=None):
    if not body.title.strip() or not body.markdown.strip():raise ServiceError(422,'名称与内容不能为空')
    source_views(db,body.sources)
    if ident:
        row=require(db,'knowledge_items',ident)
        if row['current_revision']!=body.expected_revision:raise ServiceError(409,'知识修订已变化')
        rev=row['current_revision']+1
        cur=db.execute("UPDATE knowledge_items SET title=?,current_revision=?,state='candidate',needs_review=0,updated_at=CURRENT_TIMESTAMP WHERE id=? AND current_revision=?",(body.title.strip(),rev,ident,body.expected_revision))
        if not cur.rowcount:raise ServiceError(409,'知识修订冲突')
        db.execute('DELETE FROM knowledge_sources WHERE knowledge_id=?',(ident,));db.execute('DELETE FROM knowledge_fts WHERE id=?',(ident,))
    else:
        ident=uuid.uuid4().hex;rev=1
        db.execute('INSERT INTO knowledge_items(id,title,current_revision) VALUES (?,?,?)',(ident,body.title.strip(),rev))
    refs=[r.model_dump() for r in body.sources]
    db.execute('INSERT INTO knowledge_revisions(knowledge_id,revision,markdown,sources_json,claim_type) VALUES (?,?,?,?,?)',(ident,rev,body.markdown,dump(refs),body.claim_type))
    db.executemany('INSERT INTO knowledge_sources VALUES (?,?,?)',[(ident,r.artifact_id,r.revision) for r in body.sources])
    audit(db,'knowledge',ident,'candidate',rev)
    return knowledge_view(db,ident)

def transition(db,ident,body):
    row=require(db,'knowledge_items',ident)
    if row['current_revision']!=body.expected_revision or row['state']!=body.expected_state:raise ServiceError(409,'知识状态或修订已变化，请刷新')
    pairs={('candidate','publish'):'published',('candidate','reject'):'rejected',('published','revoke'):'revoked',('rejected','reopen'):'candidate',('revoked','reopen'):'candidate'}
    target=pairs.get((row['state'],body.action))
    if not target:raise ServiceError(409,'不允许该状态变更')
    view=knowledge_view(db,ident)
    if target=='published':
        from .schemas import ArtifactSource
        sources=source_views(db,[ArtifactSource(artifact_id=s['artifact_id'],revision=s['revision']) for s in view['sources']],True)
        if view['claim_type']=='source' and not any(e.get('verification')=='quote_verified' for a in sources for e in a['evidence']):raise ServiceError(422,'原文事实需要已核验的原文引文')
    cur=db.execute('UPDATE knowledge_items SET state=?,needs_review=0,updated_at=CURRENT_TIMESTAMP WHERE id=? AND current_revision=? AND state=?',(target,ident,body.expected_revision,body.expected_state))
    if not cur.rowcount:raise ServiceError(409,'知识状态冲突')
    db.execute('DELETE FROM knowledge_fts WHERE id=?',(ident,))
    if target=='published':db.execute('INSERT INTO knowledge_fts(id,title,body) VALUES (?,?,?)',(ident,row['title'],view['markdown']))
    audit(db,'knowledge',ident,body.action,body.expected_revision)
    return knowledge_view(db,ident)

def knowledge_list(db,q='',status=None,before=None,limit=30,allowed=None,recall=False):
    clauses=['1=1'];args=[]
    if status:clauses.append('k.state=?');args.append(status)
    if before:clauses.append('k.rowid<?');args.append(before)
    if recall:
        clauses+=["k.state='published'",'k.needs_review=0',"NOT EXISTS(SELECT 1 FROM knowledge_sources s JOIN research_artifacts a ON a.id=s.artifact_id LEFT JOIN artifact_papers ap ON ap.artifact_id=a.id LEFT JOIN papers p ON p.id=ap.paper_id WHERE s.knowledge_id=k.id AND (a.archived=1 OR a.current_revision<>s.artifact_revision OR p.deleted_at IS NOT NULL))"]
    if q:
        # Literal substring works for Chinese; FTS index remains available for token matching.
        clauses.append("EXISTS(SELECT 1 FROM knowledge_revisions v WHERE v.knowledge_id=k.id AND v.revision=k.current_revision AND (instr(lower(v.markdown),lower(?))>0 OR instr(lower(k.title),lower(?))>0))");args+=[q,q]
    if allowed is not None:
        marks=','.join('?' for _ in allowed)
        clauses+=['EXISTS(SELECT 1 FROM knowledge_sources s JOIN artifact_papers p ON p.artifact_id=s.artifact_id WHERE s.knowledge_id=k.id)',f'NOT EXISTS(SELECT 1 FROM knowledge_sources s LEFT JOIN artifact_papers p ON p.artifact_id=s.artifact_id WHERE s.knowledge_id=k.id AND (p.paper_id IS NULL OR p.paper_id NOT IN ({marks})))'];args+=allowed
    rows=db.execute('SELECT k.*,k.rowid AS cursor FROM knowledge_items k WHERE '+' AND '.join(clauses)+' ORDER BY k.rowid DESC LIMIT ?',args+[limit+1]).fetchall()
    items=[knowledge_view(db,r['id'])|{'cursor':r['cursor']} for r in rows[:limit]]
    return {'knowledge':items,'has_more':len(rows)>limit,'next_before':items[-1]['cursor'] if items else None,'retrieval':'literal_text','model_called':False}


def import_existing(db,settings,limit=30):
    """Explicit projection of saved outputs; no model calls or silent knowledge publication."""
    created=[];skipped=[]
    sources=[]
    for r in db.execute("SELECT * FROM agent_runs WHERE status IN ('succeeded','failed','cancelled') AND answer<>'' AND NOT EXISTS(SELECT 1 FROM research_artifacts a WHERE a.source_key='run:'||agent_runs.id) ORDER BY rowid DESC LIMIT ?",(limit,)):
        sources.append(('run',r))
    for r in db.execute("SELECT * FROM reader_guide_tasks WHERE status IN ('published','partial') AND NOT EXISTS(SELECT 1 FROM research_artifacts a WHERE a.source_key='guide:'||reader_guide_tasks.id) ORDER BY rowid DESC LIMIT ?",(limit,)):
        sources.append(('guide',r))
    for r in db.execute("SELECT f.*,p.body_md FROM frontier_runs f JOIN frontier_reports p ON p.run_id=f.id WHERE f.status IN ('succeeded','partial') AND NOT EXISTS(SELECT 1 FROM research_artifacts a WHERE a.source_key='frontier:'||f.id) ORDER BY f.rowid DESC LIMIT ?",(limit,)):
        sources.append(('frontier',r))
    for kind,row in sources[:limit]:
        db.execute('SAVEPOINT import_source')
        try:
            if kind=='run':item=capture_run(db,settings,row['id'])
            elif kind=='guide':
                data=json.loads(row['payload_json']);summary=data.get('summary',{})
                text='\n\n'.join('## '+label+'\n\n'+summary.get(key,'') for key,label in [('problem_md','研究问题'),('approach_md','方法'),('contributions_md','贡献'),('limitations_md','局限')])
                for entry in data.get('items',[]):text+='\n\n### '+entry['title']+'\n\n'+entry['why_important_md']+'\n\n'+entry['explanation_md']
                evidence=[]
                version=db.execute('SELECT v.id FROM document_versions v JOIN paper_documents d ON d.id=v.document_id WHERE d.paper_id=? AND v.file_hash=?',(row['paper_id'],row['file_version'])).fetchone()
                if version:
                    from .schemas import Evidence
                    for resolved in data.get('_resolved',[]):
                        for anchor in resolved.get('anchors',[]):
                            if anchor.get('status')=='verified':evidence.append(Evidence(paper_id=row['paper_id'],document_version_id=version[0],file_version=row['file_version'],page=anchor['page'],quote=anchor.get('quote','')))
                body=ArtifactWrite(title='导读 · '+str(row['paper_id']),kind='guide',markdown=text[:100000],paper_ids=[row['paper_id']],evidence=evidence[:100],status='complete' if row['status']=='published' else 'partial',source_run_id=row['agent_run_id'],producer=row['skill_id'])
                item=artifact_save(db,settings,body,origin='saved_guide',source_key='guide:'+row['id'])
            else:
                body=ArtifactWrite(title='前沿报告 · '+row['window_end'],kind='frontier',markdown=row['body_md'][:100000],status='complete' if row['status']=='succeeded' else 'partial',source_run_id=row['agent_run_id'],producer='frontier_report')
                item=artifact_save(db,settings,body,origin='saved_report',source_key='frontier:'+row['id'])
            if item:created.append(item['id'])
        except (ServiceError,ValueError,KeyError,TypeError):
            db.execute('ROLLBACK TO import_source');skipped.append({'type':kind,'source_id':row['id']})
        finally:db.execute('RELEASE import_source')
    return {'created':created,'skipped':skipped,'model_called':False,'knowledge_published':False}


def reader_artifacts(db,settings,pid,file_version,limit=100):
    """A version-aware view over saved results, including legacy misclassified runs."""
    from ..reader.service import paper
    paper(db,pid)
    documents.ensure_paper(db,settings,pid)
    known=db.execute('SELECT 1 FROM document_versions v JOIN paper_documents d ON d.id=v.document_id WHERE d.paper_id=? AND v.file_hash=?',(pid,file_version)).fetchone()
    if not known:raise ServiceError(404,'原文版本不存在')
    rows=db.execute("""SELECT a.*,r.purpose AS run_purpose FROM research_artifacts a
      JOIN artifact_papers ap ON ap.artifact_id=a.id
      JOIN artifact_revisions rev ON rev.artifact_id=a.id AND rev.revision=a.current_revision
      LEFT JOIN agent_runs r ON r.id=a.source_run_id
      WHERE ap.paper_id=? AND a.archived=0 AND a.kind IN ('reading','guide')
      AND rev.status IN ('complete','partial')
      AND coalesce(r.purpose,'') NOT IN ('translate','explain','guide','skill-validation','frontier')
      AND NOT EXISTS(SELECT 1 FROM reader_guide_tasks t WHERE t.agent_run_id=a.source_run_id)
      AND coalesce(a.source_key,'') NOT LIKE 'guide:%'
      ORDER BY a.rowid DESC""",(pid,)).fetchall()
    current=[];unverified=[];older=0
    for row in rows:
        a=artifact_view(db,row['id'])
        refs=[e for e in a['evidence'] if e.get('paper_id')==pid]
        refs += [e for e in a['materials'].get('authorized',[]) if e.get('paper_id')==pid]
        hashes={e.get('file_version') for e in refs if e.get('file_version')}
        if hashes and hashes!={file_version}:older+=1;continue
        a['version_status']='matched' if hashes else 'unverified'
        (current if hashes else unverified).append(a)
    return {'artifacts':current[:limit],'unverified_artifacts':unverified[:limit],'older_versions':older,'has_more':len(current)>limit or len(unverified)>limit}
