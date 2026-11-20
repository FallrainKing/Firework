"""Deterministic manual exchange. Never dispatch an Agent run."""
import hashlib,json,secrets,time,uuid,re
from ...core.errors import ServiceError
from ...documents import service as documents
from ...papers.service import require_paper
from ...imports.sources import normalize_doi
from ...ingest.metadata import extract_arxiv_id


def dump(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(dump(value).encode()).hexdigest()
def source_digest(raw):return digest({k:v for k,v in raw.items() if k!='pdf_hash'})


def linked(db,device,library,key,pid=None):
    row=db.execute('SELECT * FROM zotero_links WHERE device_id=? AND library_key=? AND item_key=?',(device,library,key)).fetchone()
    if not row or (pid is not None and row['paper_id']!=pid):raise ServiceError(404,'同步来源未关联该论文')
    return row


def collection(db,parent,name):
    if not name.strip() or len(name)>80:raise ServiceError(422,'分类名称需为 1–80 个字符')
    row=db.execute('SELECT id FROM paper_collections WHERE parent_id IS ? AND name=?',(parent,name)).fetchone()
    if row:return row['id']
    return db.execute('INSERT INTO paper_collections(name,parent_id) VALUES (?,?)',(name,parent)).lastrowid


def import_item(db,device,body):
    raw=body.model_dump()
    if not raw.get('pdf_hash'):raw.pop('pdf_hash',None)
    if not body.title.strip():raise ServiceError(422,'标题不能为空')
    if len(dump(raw).encode())>256*1024:raise ServiceError(413,'书目信息过大')
    if any(len(a)>240 or not a.strip() for a in body.authors):raise ServiceError(422,'作者字段无效')
    if any(len(t)>100 or not t.strip() for t in body.tags):raise ServiceError(422,'标签字段无效')
    for path in body.collection_paths:
        if not path or len(path)>10 or any(not n.strip() or len(n)>80 for n in path):raise ServiceError(422,'分类层级或名称超出范围')
    prior=db.execute('SELECT * FROM zotero_links WHERE device_id=? AND library_key=? AND item_key=?',(device['id'],body.library_key,body.item_key)).fetchone()
    if prior and prior['source_hash']==source_digest(raw):return {'paper_id':prior['paper_id'],'deduplicated':True}
    try:
        doi=normalize_doi(body.doi) if body.doi.strip() else None
        arxiv=extract_arxiv_id(body.arxiv_id) if body.arxiv_id.strip() else None
    except ValueError as e:raise ServiceError(422,str(e))
    row=require_paper(db,prior['paper_id']) if prior else None
    if not row and doi:row=db.execute('SELECT * FROM papers WHERE doi=?',(doi,)).fetchone()
    if not row and arxiv:row=db.execute('SELECT * FROM papers WHERE arxiv_id=?',(arxiv,)).fetchone()
    if not row and body.pdf_hash:
        matches=db.execute('SELECT DISTINCT p.* FROM papers p JOIN paper_documents d ON d.paper_id=p.id JOIN document_versions v ON v.document_id=d.id WHERE v.file_hash=?',(body.pdf_hash,)).fetchall()
        if len(matches)>1:raise ServiceError(409,'同一 PDF 已关联多篇论文，请先在论文库人工核对，未创建新条目')
        if matches:row=matches[0]
    if row and ((doi and row['doi'] and doi!=row['doi']) or (arxiv and row['arxiv_id'] and arxiv!=row['arxiv_id'])):raise ServiceError(409,'DOI 与 arXiv 身份冲突，请人工核对')
    if row:
        for field,value in (('doi',doi),('arxiv_id',arxiv)):
            if value and db.execute(f'SELECT 1 FROM papers WHERE {field}=? AND id<>?',(value,row['id'])).fetchone():raise ServiceError(409,'该标识已关联另一篇论文，请人工核对；未合并或创建副本')
    if prior and row['metadata_version']!=prior['metadata_version']:raise ServiceError(409,'Firework 书目已修改，未覆盖；请先人工处理差异')
    with db:
        if row:
            pid=row['id']
            if prior:
                db.execute('UPDATE papers SET title=?,authors=?,abstract=?,doi=coalesce(doi,?),arxiv_id=coalesce(arxiv_id,?),source_url=?,metadata_version=metadata_version+1 WHERE id=?',(body.title.strip(),dump(body.authors),body.abstract,doi,arxiv,body.url or row['source_url'],pid))
        else:
            pid=db.execute("INSERT INTO papers(title,authors,abstract,doi,arxiv_id,source,source_url) VALUES (?,?,?,?,?,'import',?)",(body.title.strip(),dump(body.authors),body.abstract,doi,arxiv,body.url or None)).lastrowid
        if body.collection_paths:
            root=collection(db,None,'Zotero · '+device['name'][:48]+' '+device['id'][:6])
            library=collection(db,root,body.library_key[:80])
            for path in body.collection_paths:
                parent=library
                for part in path:parent=collection(db,parent,part)
                db.execute('INSERT OR IGNORE INTO paper_collection_items(collection_id,paper_id) VALUES (?,?)',(parent,pid))
        for tag in body.tags:db.execute('INSERT OR IGNORE INTO paper_tags(paper_id,tag,source_device) VALUES (?,?,?)',(pid,tag,device['id']))
        revision=require_paper(db,pid)['metadata_version']
        db.execute('''INSERT INTO zotero_links(device_id,library_key,item_key,paper_id,source_json,source_hash,metadata_version)
          VALUES (?,?,?,?,?,?,?) ON CONFLICT(device_id,library_key,item_key) DO UPDATE SET
          source_json=excluded.source_json,source_hash=excluded.source_hash,metadata_version=excluded.metadata_version,updated_at=CURRENT_TIMESTAMP''',(device['id'],body.library_key,body.item_key,pid,dump(raw),source_digest(raw),revision))
    return {'paper_id':pid,'deduplicated':False,'matched_existing':bool(row and not prior)}


async def attachment(state,device,pid,library,item_key,attachment_key,data,label,filename,role):
    db=state.db;linked(db,device,library,item_key,pid)
    old=db.execute('SELECT * FROM zotero_attachment_links WHERE device_id=? AND library_key=? AND attachment_key=?',(device,library,attachment_key)).fetchone()
    if old and old['item_key']!=item_key:raise ServiceError(409,'附件已绑定其他条目')
    same=db.execute("SELECT v.document_id FROM document_versions v JOIN paper_documents d ON d.id=v.document_id WHERE d.paper_id=? AND v.file_hash=? ORDER BY CASE d.role WHEN 'main' THEN 0 ELSE 1 END LIMIT 1",(pid,hashlib.sha256(data).hexdigest())).fetchone() if not old else None
    v=documents.add_version(db,state.settings,pid,data,label=label,filename=filename,document_id=old['document_id'] if old else (same['document_id'] if same else None),role=role,title='正文' if role=='main' else label,source='Zotero · '+library,description='由用户手动发送；保留原件')
    row=documents.version(db,pid,v['version_id'])
    with db:
        db.execute('''INSERT INTO zotero_attachment_links VALUES (?,?,?,?,?,?,?) ON CONFLICT(device_id,library_key,attachment_key)
          DO UPDATE SET version_id=excluded.version_id,file_hash=excluded.file_hash''',(device,library,attachment_key,item_key,row['document_id'],row['id'],row['file_hash']))
    # Transfer completion must not wait for CPU-heavy vector indexing.
    # Only first-time reading activation is cheap; later version changes keep the index-switch contract.
    if row['role']=='main' and require_paper(db,pid)['default_version_id'] is None:
        with db:
            db.execute('UPDATE papers SET pdf_path=?,default_version_id=? WHERE id=? AND default_version_id IS NULL',(str(documents.asset_path(state.settings,row['storage_key'])),row['id'],pid))
            db.execute('UPDATE paper_documents SET current_version_id=? WHERE id=?',(row['id'],row['document_id']))
    indexed=bool(db.execute('SELECT 1 FROM chunks_meta WHERE paper_id=? LIMIT 1',(pid,)).fetchone())
    return {**v,'has_default_pdf':bool(require_paper(db,pid)['default_version_id']),'fulltext_indexed':indexed}


def collection_paths(db,pid):
    paths=[]
    origins=db.execute('SELECT device_id,library_key FROM zotero_links WHERE paper_id=?',(pid,)).fetchall()
    for row in db.execute('SELECT collection_id FROM paper_collection_items WHERE paper_id=?',(pid,)):
        chain=[];ident=row[0];seen=set()
        while ident and ident not in seen:
            seen.add(ident);node=db.execute('SELECT * FROM paper_collections WHERE id=?',(ident,)).fetchone()
            if not node:break
            chain.append(node['name']);ident=node['parent_id']
        path=chain[::-1]
        if len(path)>=3 and any(path[0].startswith('Zotero · ') and path[0].endswith(' '+o['device_id'][:6]) and path[1]==o['library_key'] for o in origins):path=path[2:]
        if path not in paths:paths.append(path)
    return paths


def enqueue(db,settings,device_id,pid,key):
    prior=db.execute('SELECT e.* FROM zotero_export_request_keys k JOIN zotero_exports e ON e.id=k.export_id WHERE k.request_key=?',(key,)).fetchone()
    if prior:
        if prior['device_id']!=device_id or prior['paper_id']!=pid:raise ServiceError(409,'请求编号已用于其他任务')
        return {'id':prior['id'],'status':prior['status']}
    p=require_paper(db,pid);listed=documents.list_documents(db,settings,pid)
    link=db.execute('SELECT * FROM zotero_links WHERE device_id=? AND paper_id=? ORDER BY updated_at DESC LIMIT 1',(device_id,pid)).fetchone()
    files=[]
    for doc in listed['documents']:
        for v in doc['versions']:
            if v['available']:
                files.append({'version_id':v['id'],'file_hash':v['file_hash'],'label':v['label'],'role':doc['role'],'document_title':doc['title'],'is_default':v['is_default'],'size':v['size']})
    if len(files)>30:raise ServiceError(422,'单篇超过 30 个附件，请先缩小同步范围')
    payload={'paper_id':pid,'title':p['title'],'authors':json.loads(p['authors'] or '[]'),'abstract':p['abstract'] or '', 'doi':p['doi'] or '', 'arxiv_id':p['arxiv_id'] or '', 'url':p['source_url'] or ('https://arxiv.org/abs/'+p['arxiv_id'] if p['arxiv_id'] else ''),
      'tags':[r[0] for r in db.execute('SELECT DISTINCT tag FROM paper_tags WHERE paper_id=?',(pid,))], 'collection_paths':collection_paths(db,pid),
      'library_key':link['library_key'] if link else None,'item_key':link['item_key'] if link else None,'files':files}
    duplicate=db.execute("SELECT id,status FROM zotero_exports WHERE device_id=? AND paper_id=? AND payload_json=? AND status IN ('pending','leased') ORDER BY rowid LIMIT 1",(device_id,pid,dump(payload))).fetchone()
    if duplicate:
        with db:db.execute('INSERT INTO zotero_export_request_keys VALUES (?,?)',(key,duplicate['id']))
        return dict(duplicate)
    ident=uuid.uuid4().hex
    with db:
        db.execute('INSERT INTO zotero_exports(id,device_id,paper_id,request_key,payload_json) VALUES (?,?,?,?,?)',(ident,device_id,pid,key,dump(payload)))
        db.execute('INSERT INTO zotero_export_request_keys VALUES (?,?)',(key,ident))
    return {'id':ident,'status':'pending'}


def claim_export(db,device):
    now=int(time.time())
    row=db.execute("SELECT * FROM zotero_exports WHERE device_id=? AND (status='pending' OR (status='leased' AND lease_until<?)) ORDER BY created_at,rowid LIMIT 1",(device,now)).fetchone()
    if not row:return {'job':None}
    token=secrets.token_urlsafe(24)
    with db:db.execute("UPDATE zotero_exports SET status='leased',lease_token=?,lease_until=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(token,now+900,row['id']))
    payload=json.loads(row['payload_json'])
    link=db.execute('SELECT library_key,item_key FROM zotero_links WHERE device_id=? AND paper_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 1',(device,row['paper_id'])).fetchone()
    if link:payload.update(dict(link))
    return {'job':{'id':row['id'],'payload':payload,'lease_token':token,'lease_seconds':900}}


def export_job(db,device,ident,lease):
    r=db.execute("SELECT * FROM zotero_exports WHERE id=? AND device_id=? AND status='leased' AND lease_token=? AND lease_until>?",(ident,device,lease,int(time.time()))).fetchone()
    if not r:raise ServiceError(409,'任务租约失效，请重新领取')
    return r


def acknowledge(db,device,ident,body):
    previous=db.execute('SELECT * FROM zotero_exports WHERE id=? AND device_id=? AND lease_token=?',(ident,device,body.lease_token)).fetchone()
    result=dump(body.model_dump(exclude={'lease_token'}))
    if previous and previous['status'] in ('completed','failed') and previous['result_json']==result:return {'saved':True}
    r=export_job(db,device,ident,body.lease_token);payload=json.loads(r['payload_json'])
    if body.success and (not body.library_key or not re.fullmatch(r'[A-Z0-9]{8}',body.item_key)):raise ServiceError(422,'缺少 Zotero 条目确认信息')
    if body.success:
        if set(body.attachments)!={f['version_id'] for f in payload['files']}:raise ServiceError(422,'附件确认数量不完整')
        existing=db.execute('SELECT paper_id FROM zotero_links WHERE device_id=? AND library_key=? AND item_key=?',(device,body.library_key,body.item_key)).fetchone()
        if existing and existing['paper_id']!=r['paper_id']:raise ServiceError(409,'目标 Zotero 条目已关联其他论文')
        for vid,akey in body.attachments.items():
            prior=db.execute('SELECT * FROM zotero_attachment_links WHERE device_id=? AND library_key=? AND attachment_key=?',(device,body.library_key,akey)).fetchone()
            if prior and (prior['item_key']!=body.item_key or prior['file_hash']!=documents.version(db,r['paper_id'],vid)['file_hash']):raise ServiceError(409,'目标 Zotero 附件已关联其他内容')
    with db:
        db.execute('UPDATE zotero_exports SET status=?,result_json=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',('completed' if body.success else 'failed',dump(body.model_dump(exclude={'lease_token'})),body.error or None,ident))
        if body.success:
            # Keep a source mapping without treating an export as a Zotero metadata overwrite.
            paper=require_paper(db,r['paper_id'])
            db.execute('''INSERT OR IGNORE INTO zotero_links VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)''',(device,body.library_key,body.item_key,r['paper_id'],dump({'exported':True}),digest({'exported':True}),paper['metadata_version']))
            for vid,akey in body.attachments.items():
                f=next((f for f in payload['files'] if f['version_id']==vid),None)
                if not f or not re.fullmatch(r'[A-Z0-9]{8}',akey):raise ServiceError(422,'附件确认信息不匹配')
                v=documents.version(db,r['paper_id'],vid)
                db.execute('INSERT OR IGNORE INTO zotero_attachment_links VALUES (?,?,?,?,?,?,?)',(device,body.library_key,akey,body.item_key,v['document_id'],vid,v['file_hash']))
    return {'saved':True}


def recover_first_pdfs(db,settings):
    """Repair completed Zotero file transfers interrupted before reading activation.

    Only verified source-linked main PDFs with no previous reading material or index
    qualify. Never choose a new version for an existing reader or merge papers.
    """
    rows=db.execute('''SELECT DISTINCT d.paper_id,v.id,v.document_id,v.file_hash,f.storage_key,v.created_at
      FROM papers p JOIN paper_documents d ON d.paper_id=p.id
      JOIN document_versions v ON v.document_id=d.id
      JOIN zotero_attachment_links a ON a.version_id=v.id AND a.document_id=d.id
      JOIN file_objects f ON f.hash=v.file_hash
      WHERE p.default_version_id IS NULL AND p.pdf_path IS NULL AND d.role='main'
      AND NOT EXISTS(SELECT 1 FROM chunks_meta c WHERE c.paper_id=p.id)
      ORDER BY v.created_at,v.id''').fetchall()
    repaired=0
    for r in rows:
        try:
            path=documents.asset_path(settings,r['storage_key'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=r['file_hash']:continue
        except (OSError,ValueError,ServiceError):continue
        with db:
            result=db.execute('UPDATE papers SET pdf_path=?,default_version_id=? WHERE id=? AND pdf_path IS NULL AND default_version_id IS NULL',(str(path),r['id'],r['paper_id']))
            if result.rowcount:
                db.execute('UPDATE paper_documents SET current_version_id=? WHERE id=?',(r['id'],r['document_id']))
                repaired+=1
    return repaired
