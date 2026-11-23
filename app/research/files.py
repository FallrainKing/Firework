"""Immutable evidence/asset uploads: bounded types, no executable HTML or paths."""
import hashlib
import os
from pathlib import Path
import uuid
from ..core.errors import ServiceError

MAX_SIZE=30*1024*1024

def store(db,settings,pid,filename,data):
    if not db.execute('SELECT 1 FROM papers WHERE id=? AND deleted_at IS NULL',(pid,)).fetchone():raise ServiceError(404,'关联论文不存在')
    if not data or len(data)>MAX_SIZE:raise ServiceError(422,'文件为空或超过30MiB')
    suffix=Path(filename).suffix.lower();mime=None
    if suffix=='.pdf' and data.startswith(b'%PDF-'):
        from ..documents.service import inspect_pdf
        inspect_pdf(data);mime='application/pdf'
    elif suffix=='.png' and data.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
    elif suffix in ('.jpg','.jpeg') and data.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
    elif suffix in ('.txt','.md','.json'):
        try:data.decode('utf-8')
        except UnicodeDecodeError:raise ServiceError(422,'文本文件必须为UTF-8') from None
        mime='text/plain'
    if not mime:raise ServiceError(422,'支持PDF、PNG、JPEG、TXT、Markdown和JSON')
    digest=hashlib.sha256(data).hexdigest();root=settings.data_dir/'research-files';root.mkdir(mode=0o700,exist_ok=True)
    path=root/digest
    if path.is_symlink() or root.is_symlink():raise ServiceError(409,'文件目录无效')
    old=db.execute('SELECT * FROM research_files WHERE hash=?',(digest,)).fetchone()
    if old and old['paper_id']!=pid:raise ServiceError(409,'该文件已归属另一论文，请复用对应产物')
    if path.exists():
        with path.open("rb") as existing:
            if hashlib.file_digest(existing,"sha256").hexdigest()!=digest:raise ServiceError(409,"文件校验失败")
    if not path.exists():
        temp=root/('.'+uuid.uuid4().hex)
        try:temp.write_bytes(data);temp.chmod(0o400);temp.replace(path)
        finally:temp.unlink(missing_ok=True)
    db.execute('INSERT OR IGNORE INTO research_files(hash,paper_id,filename,mime,size) VALUES (?,?,?,?,?)',(digest,pid,Path(filename).name[:160],mime,len(data)))
    return dict(db.execute('SELECT * FROM research_files WHERE hash=?',(digest,)).fetchone())

def resolve(db,settings,ident):
    if len(ident)!=64 or any(c not in '0123456789abcdef' for c in ident):raise ServiceError(404,'文件不存在')
    r=db.execute('SELECT * FROM research_files WHERE hash=?',(ident,)).fetchone()
    if not r:raise ServiceError(404,'文件不存在')
    p=settings.data_dir/'research-files'/ident
    if p.is_symlink() or not p.is_file():raise ServiceError(404,'文件不可用')
    with p.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual!=ident:raise ServiceError(409,'文件校验失败')
    return r,p
