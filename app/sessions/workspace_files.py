"""Descriptor-relative access to a terminal's own workspace, with no symlink traversal."""
import hashlib
import os
from pathlib import Path,PurePosixPath
import stat
from ..core.errors import ServiceError
from .terminal import require_terminal

MAX_BYTES=30*1024*1024

def root(state,ident):
    require_terminal(state.db,ident)
    return state.settings.data_dir/'agent/terminals'/str(ident)/'workspace'

def read(state,ident,name,expected=None):
    base=root(state,ident);relative=PurePosixPath(name)
    if not relative.parts or str(relative)!=name or relative.is_absolute() or '..' in relative.parts or '\\' in name:raise ServiceError(422,'文件路径无效')
    descriptors=[]
    try:
        fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);descriptors.append(fd)
        for part in relative.parts[:-1]:
            fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);descriptors.append(fd)
        leaf=os.open(relative.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd);descriptors.append(leaf)
        info=os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_BYTES:raise ServiceError(422,'只能读取30MiB以内的普通文件')
        data=bytearray()
        while chunk:=os.read(leaf,65536):
            data.extend(chunk)
            if len(data)>MAX_BYTES:raise ServiceError(422,'文件超过大小限制')
        digest=hashlib.sha256(data).hexdigest()
        if expected and digest!=expected:raise ServiceError(409,'文件已变化，请刷新列表')
        return bytes(data),digest
    except OSError:raise ServiceError(404,'工作文件不存在或不可访问') from None
    finally:
        for fd in reversed(descriptors):os.close(fd)

def listing(state,ident):
    base=root(state,ident);items=[];hashed=0
    if not base.is_dir():return {'files':[]}
    for folder,dirs,names in os.walk(base,followlinks=False):
        dirs[:]=[n for n in dirs if not n.startswith('.') and not (Path(folder)/n).is_symlink()]
        for name in sorted(names):
            path=Path(folder)/name
            if path.is_symlink():continue
            try:size=path.stat().st_size
            except OSError:continue
            relative=path.relative_to(base).as_posix();digest=None
            if size<=MAX_BYTES and hashed+size<=100*1024*1024:
                try:_,digest=read(state,ident,relative);hashed+=size
                except ServiceError:continue
            items.append({'path':relative,'size':size,'sha256':digest})
            if len(items)>=100:return {'files':items,'truncated':True}
    return {'files':items,'truncated':False}
