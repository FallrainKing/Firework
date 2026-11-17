"""Original-page evidence and reader geometry, independent of legacy RAG pages."""
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import pymupdf

@lru_cache(maxsize=128)
def _fingerprint(path,mtime,size):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def pdf_file(settings,row):
    if not row['pdf_path']:raise ValueError('这篇论文尚无 PDF 全文，请先添加文件。')
    root=(settings.data_dir/'papers').resolve()
    path=Path(row['pdf_path'])
    if str(path).startswith('/app/data/papers/'):
        path=root/path.name
    path=path.resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('PDF 文件不可用')
    stat=path.stat()
    return path,_fingerprint(str(path),stat.st_mtime_ns,stat.st_size)

def document_info(settings,row):
    path,version=pdf_file(settings,row)
    return _document_info(str(path),version,row['id'],row['title'])

@lru_cache(maxsize=64)
def _document_info(path,version,paper_id,title):
    from .rag.pdf_parser import extract_pages,split_sections,FRONT_MATTER_TITLE
    with pymupdf.open(path) as doc:
        if doc.is_encrypted:raise ValueError('暂不支持加密 PDF')
        if not 0<len(doc)<=300:raise ValueError('PDF 页数必须为 1–300')
        outline=[{'level':int(level),'title':label,'page':page} for level,label,page,*_ in doc.get_toc() if 1<=page<=len(doc)]
        if not outline:
            outline=[{'level':1,'title':section.title,'page':section.page} for section in split_sections(extract_pages(path)) if section.title!=FRONT_MATTER_TITLE][:120]
        first=doc[0].rect
        return {'paper_id':paper_id,'title':title,'file_version':version,'page_count':len(doc),'width':first.width,'height':first.height,'outline':outline,'pdf_url':f"/api/reader/papers/{paper_id}/file"}

def read_page(settings,row,page):
    path,version=pdf_file(settings,row)
    with pymupdf.open(path) as doc:
        if not 1<=page<=len(doc):raise ValueError('页码超出范围')
        p=doc[page-1]
        return {'paper_id':row['id'],'title':row['title'],'page':page,'file_version':version,'width':p.rect.width,'height':p.rect.height,'text':p.get_text('text',sort=True),'text_source':'original_pdf_page','figures_read':False}

def normalize(text):
    return re.sub(r'\s+','',text).replace('\u00ad','').replace('−','-').replace('–','-')

def validate_context(settings,db,context,conversation_id=None):
    if conversation_id is not None and not db.execute('SELECT 1 FROM conversation_papers WHERE conversation_id=? AND paper_id=?',(conversation_id,context['paper_id'])).fetchone():raise ValueError('论文未关联当前会话')
    row=db.execute('SELECT * FROM papers WHERE id=?',(context['paper_id'],)).fetchone()
    if row is None:raise ValueError('论文不存在')
    data=read_page(settings,row,context['page'])
    if data['file_version']!=context['file_version']:raise ValueError('PDF 版本已变化，请重新选择原文')
    quote=context.get('quote','').strip()
    # PDF.js and PyMuPDF can differ in ligatures/hyphens/reading order.
    # Preserve captured geometry, but never overstate a failed text match.
    located=bool(quote and normalize(quote) in normalize(data['text']))
    return {**context,'quote':quote,'validation':'text_located' if located else 'page_captured','source':'original_pdf_page'}
