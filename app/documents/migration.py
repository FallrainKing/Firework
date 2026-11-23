"""Explicit, previewed text-anchor migration. Drawings and ambiguous matches stay put."""
import hashlib
import json
import re
import pymupdf
from pydantic import BaseModel,Field
from ..core.errors import ServiceError
from ..reader.schemas import Annotation
from ..reader.service import insert_annotation_record
from . import service as documents

class Preview(BaseModel):
    source_version_id:str=Field(min_length=1,max_length=64)
    target_version_id:str=Field(min_length=1,max_length=64)
    annotation_ids:list[str]=Field(min_length=1,max_length=30)

class Confirm(Preview):
    confirmation_hash:str=Field(pattern='^[a-f0-9]{64}$')

def preview(db,settings,pid,body):
    source=documents.version(db,pid,body.source_version_id);target=documents.version(db,pid,body.target_version_id)
    if source['id']==target['id']:raise ServiceError(422,'请选择不同文件版本')
    items=[];path=documents.asset_path(settings,target['storage_key'])
    with pymupdf.open(path) as pdf:
        for ident in list(dict.fromkeys(body.annotation_ids)):
            old=db.execute('SELECT * FROM reader_annotations WHERE id=? AND paper_id=? AND file_version=? AND deleted=0',(ident,pid,source['file_hash'])).fetchone()
            if not old:raise ServiceError(404,'来源批注不存在')
            matches=[]
            if old['quote'] and old['kind'] in ('highlight','note'):
                for page in pdf:
                    rects=page.search_for(old['quote'])
                    normalize=lambda x:re.sub(r'\s+','',x).casefold()
                    if rects and len(rects)<=100 and normalize(page.get_text()).count(normalize(old['quote']))==1:matches.append({'page':page.number+1,'rects':[[r.x0/page.rect.width,r.y0/page.rect.height,r.width/page.rect.width,r.height/page.rect.height] for r in rects]})
            eligible=len(matches)==1
            old_digest=hashlib.sha256(json.dumps(dict(old),sort_keys=True).encode()).hexdigest()
            items.append({'source_id':ident,'source_etag':old_digest,'kind':old['kind'],'quote':old['quote'],'content':old['content'],'color':old['color'],'eligible':eligible,'reason':None if eligible else '未找到唯一文字位置，保留原批注','target':matches[0] if eligible else None})
    plan={'paper_id':pid,'source_version_id':source['id'],'target_version_id':target['id'],'target_hash':target['file_hash'],'items':items}
    return plan|{'confirmation_hash':hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}

def apply(db,settings,pid,body):
    plan=preview(db,settings,pid,body)
    if body.confirmation_hash!=plan['confirmation_hash']:raise ServiceError(409,'批注或文件已变化，请重新预览')
    copied=[];skipped=[]
    with db:
        for item in plan['items']:
            if not item['eligible']:skipped.append(item['source_id']);continue
            prior=db.execute('SELECT target_id FROM annotation_migrations WHERE source_id=? AND target_version_id=?',(item['source_id'],body.target_version_id)).fetchone()
            if prior:copied.append(prior[0]);continue
            new=Annotation(paper_id=pid,file_version=plan['target_hash'],page=item['target']['page'],kind=item['kind'],quote=item['quote'],rects=item['target']['rects'],content=item['content'],color=item['color'])
            aid=insert_annotation_record(db,new)
            db.execute('UPDATE reader_annotations SET document_version_id=? WHERE id=?',(body.target_version_id,aid))
            db.execute('INSERT INTO annotation_migrations(source_id,target_version_id,target_id) VALUES (?,?,?)',(item['source_id'],body.target_version_id,aid));copied.append(aid)
    return {'copied_ids':copied,'skipped_ids':skipped,'originals_unchanged':True}
