"""Resolve source anchors against the exact PDF, never guessed coordinates."""
import hashlib
import re
import pymupdf
from ..core.errors import ServiceError
from . import service,pages

def locate(db,settings,body):
    pid=body.paper_id;p=service.paper(db,pid)
    from ..documents import service as docs
    docs.ensure_paper(db,settings,pid)
    row=db.execute('SELECT v.id,f.storage_key FROM document_versions v JOIN paper_documents d ON d.id=v.document_id JOIN file_objects f ON f.hash=v.file_hash WHERE d.paper_id=? AND v.file_hash=?',(pid,body.file_version)).fetchone()
    if row:path=docs.asset_path(settings,row['storage_key'])
    else:
        path,digest=pages.pdf_file(settings,p)
        if digest!=body.file_version:raise ServiceError(409,'原文版本已不可用')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=body.file_version:raise ServiceError(409,'文件校验失败')
    result={'paper_id':pid,'file_version':body.file_version,'document_version_id':row['id'] if row else None,'page':body.page,'quote':body.quote,'rects':[],'status':'page_only'}
    with pymupdf.open(path) as pdf:
        if body.page>len(pdf):raise ServiceError(422,'原文页码无效')
        page=pdf[body.page-1];text=page.get_text();normalize=lambda t:re.sub(r'\s+','',t).casefold()
        if body.quote.strip():
            count=normalize(text).count(normalize(body.quote))
            matches=[r*page.rotation_matrix for r in page.search_for(body.quote)]
            if count==1 and matches:
                result.update(status='located',rects=[[r.x0/page.rect.width,r.y0/page.rect.height,r.width/page.rect.width,r.height/page.rect.height] for r in matches[:100]])
            elif count>1 and body.rects:
                # Supplied selected geometry disambiguates only when it intersects a real text match.
                areas=[pymupdf.Rect(r[0]*page.rect.width,r[1]*page.rect.height,(r[0]+r[2])*page.rect.width,(r[1]+r[3])*page.rect.height) for r in body.rects]
                chosen=[r for r in matches if any((r&a).get_area()>=r.get_area()*.5 for a in areas)]
                if chosen:result.update(status='located',rects=[[r.x0/page.rect.width,r.y0/page.rect.height,r.width/page.rect.width,r.height/page.rect.height] for r in chosen[:100]])
                else:result['status']='ambiguous'
            elif count>1:result['status']='ambiguous'
    if row:result['original_url']=f'/api/library/papers/{pid}/document-versions/{row["id"]}/file?inline=true#page={body.page}'
    return result
