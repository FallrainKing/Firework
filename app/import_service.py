"""Agent-invoked import tool. Deterministic I/O, parsing and indexing only."""
import hashlib
import json
import re
from pathlib import Path
import tempfile
import pymupdf
from .ingest.pipeline import ingest_paper
from .paper_sources import fetch_pdf,doi_metadata,arxiv_metadata,normalize_doi
from .ingest.metadata import extract_arxiv_id
from .reader_store import pdf_file


def pdf_metadata(path,filename):
    with pymupdf.open(path) as doc:
        if doc.is_encrypted or not 1<=len(doc)<=300:raise ValueError('只支持 1–300 页且未加密的 PDF')
        if not any(page.get_text().strip() for page in doc):raise ValueError('PDF 没有可索引的文字层，暂不支持扫描件 OCR')
        meta=doc.metadata or {}
        title=(meta.get('title') or '').strip()
        if not title or len(title)>400 or title.lower() in ('untitled','latex document'):title=Path(filename).stem
        author=(meta.get('author') or '').strip()
        return {'title':title,'authors':[author] if author else [],'abstract':'','affiliations':[]}

def local_arxiv(db,settings,ident):
    found=db.execute('SELECT * FROM papers WHERE arxiv_id=?',(ident,)).fetchone()
    if found:return found
    # Old uploads may lack IDs. Accept only the standard rotated arXiv
    # watermark on the first page, never a matching title or reference.
    for old in db.execute('SELECT * FROM papers WHERE arxiv_id IS NULL AND pdf_path IS NOT NULL LIMIT 200').fetchall():
        try:
            path,_=pdf_file(settings,old)
            with pymupdf.open(path) as doc:
                page=doc[0]
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines',[]):
                        if abs(line.get('dir',[1,0])[0])>.1 or line['bbox'][0]>page.rect.width*.15:continue
                        text=''.join(span.get('text','') for span in line['spans']).strip()
                        match=re.match(r'^arXiv:\s*([^\s]+)\s+\[[^\]]+\]',text)
                        if match and extract_arxiv_id(match[1])==ident:
                            db.execute('UPDATE papers SET arxiv_id=? WHERE id=? AND arxiv_id IS NULL',(ident,old['id']));db.commit()
                            return db.execute('SELECT * FROM papers WHERE id=?',(old['id'],)).fetchone()
        except (ValueError,RuntimeError,OSError):continue
    return None

async def process_import(row,db,settings,embedder,store):
    # Completion is idempotent even if the CLI response was previously lost.
    if row['status']=='completed':return {'paper_id':row['paper_id'],'message':row['message'],'already_imported':True}
    data=None;meta={};target=row['target_paper_id'] or row['paper_id']
    if target:
        existing=db.execute('SELECT * FROM papers WHERE id=?',(target,)).fetchone()
        if existing is None:raise ValueError('目标论文不存在')
        if existing['pdf_path']:return {'paper_id':target,'title':existing['title'],'has_pdf':True,'message':'该论文已有 PDF，保留原文件，未覆盖。'}
    if row['channel']=='upload':
        path=(settings.data_dir/'imports'/f"{row['id']}.pdf").resolve()
        if not path.is_relative_to((settings.data_dir/'imports').resolve()) or not path.exists():raise ValueError('上传文件已不可用，请重新上传')
        meta=pdf_metadata(path,row['original_filename'] or 'upload.pdf');data=path.read_bytes()
    elif row['channel']=='arxiv':
        ident=extract_arxiv_id(row['source_value'])
        found=local_arxiv(db,settings,ident)
        if found:
            if found['pdf_path']:return {'paper_id':found['id'],'title':found['title'],'has_pdf':True,'message':'论文已在库中，复用已有全文。'}
            target=found['id']
        meta=await arxiv_metadata(row['source_value'])
        data=await fetch_pdf('https://arxiv.org/pdf/'+meta['arxiv_id'])
    elif row['channel']=='doi':
        found=db.execute('SELECT * FROM papers WHERE doi=?',(normalize_doi(row['source_value']),)).fetchone()
        if found:return {'paper_id':found['id'],'title':found['title'],'has_pdf':bool(found['pdf_path']),'message':'复用已有 DOI 条目。'}
        meta=await doi_metadata(row['source_value'])
        # DOI gives a verified bibliography, not guaranteed open full text.
    elif row['channel']=='url':
        data=await fetch_pdf(row['source_value'])
        with tempfile.NamedTemporaryFile(suffix='.pdf') as temp:
            temp.write(data);temp.flush();meta=pdf_metadata(Path(temp.name),'linked-paper.pdf')
    if data is not None:
        with tempfile.NamedTemporaryFile(suffix='.pdf') as checked:
            checked.write(data);checked.flush();pdf_metadata(Path(checked.name),'paper.pdf')
        digest=hashlib.sha256(data).hexdigest()
        for old in db.execute('SELECT * FROM papers WHERE pdf_path IS NOT NULL'):
            try:
                _,old_digest=pdf_file(settings,old)
                if digest==old_digest:return {'paper_id':old['id'],'title':old['title'],'has_pdf':True,'message':'文件内容已存在，复用已有论文。'}
            except (ValueError,OSError):continue
    if target:
        old=db.execute('SELECT * FROM papers WHERE id=?',(target,)).fetchone()
        meta={**meta,'title':old['title'] or meta.get('title',''),'authors':json.loads(old['authors'] or '[]') or meta.get('authors',[]),'abstract':old['abstract'] or meta.get('abstract',''),'arxiv_id':old['arxiv_id'] or meta.get('arxiv_id')}
        paper_id=target
    else:
        cur=db.execute("INSERT INTO papers(title,authors,abstract,arxiv_id,categories,source,doi,source_url,affiliations,affiliation_source) VALUES (?,?,?,?,?,'import',?,?,?,?)",(meta.get('title') or '待补全论文',json.dumps(meta.get('authors',[]),ensure_ascii=False),meta.get('abstract',''),meta.get('arxiv_id'),json.dumps(meta.get('categories',[])),meta.get('doi'),meta.get('url') or (row['source_value'] if row['channel']=='url' else None),json.dumps(meta.get('affiliations',[]),ensure_ascii=False),'crossref' if meta.get('affiliations') else 'missing'))
        paper_id=cur.lastrowid
    db.execute('UPDATE import_requests SET paper_id=? WHERE id=?',(paper_id,row['id']));db.commit()
    if data is not None:
        with tempfile.NamedTemporaryFile(suffix='.pdf') as temp:
            temp.write(data);temp.flush()
            await ingest_paper(Path(temp.name),source='arxiv' if row['channel']=='arxiv' else 'import',arxiv_id=meta.get('arxiv_id'),title=meta.get('title') or '待补全论文',authors=meta.get('authors',[]),abstract=meta.get('abstract',''),categories=meta.get('categories',[]),db=db,embedder=embedder,store=store,data_dir=settings.data_dir,existing_paper_id=paper_id)
    return {'paper_id':paper_id,'title':meta.get('title'),'has_pdf':data is not None,'message':'全文已保存并完成索引。' if data is not None else '已保存 DOI 书目信息，全文尚未添加，可继续上传 PDF。'}
