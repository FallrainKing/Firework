"""Read only Firework-bound native transcripts, never the host's global history."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from fastapi import HTTPException

MAX_SCAN = 4 * 1024 * 1024
MAX_LINE = 1024 * 1024


def binding(runtime, conversation_id, allow_legacy=False):
    with sqlite3.connect((Path(runtime).parent/'app.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT native_session_id,runner_connection_json,execution_mode FROM conversations WHERE id=?',(conversation_id,)).fetchone()
    if not row:raise HTTPException(404,'会话不存在')
    sid=row['native_session_id']
    if not sid or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',sid):raise HTTPException(409,'会话尚未绑定原生标识')
    if row['execution_mode']=='terminal':return sid,Path(runtime)/'terminals'/str(conversation_id)/'config'
    config=Path(runtime)/'claude-config'
    snap=json.loads(row['runner_connection_json'] or '{}')
    if snap.get('mode')=='custom':
        if not re.fullmatch(r'[a-f0-9]{32}',str(snap.get('id',''))) or not isinstance(snap.get('revision'),int) or snap['revision']<1:raise HTTPException(409,'会话连接绑定无效')
        config=Path(runtime)/'connections'/f"{snap['id']}-{snap['revision']}"/'claude-config'
    elif not allow_legacy:
        # Non-primary workspaces must never fall back to a host configuration.
        raise HTTPException(409,'该会话尚未绑定自己的模型连接')
    return sid,config


def safe_path(path, root):
    """Reject links at every component before opening a managed file."""
    try:
        relative=path.absolute().relative_to(root.absolute())
    except ValueError:raise HTTPException(409,'原生资源路径无效') from None
    current=root
    if current.is_symlink():raise HTTPException(409,'原生资源不允许链接')
    for part in relative.parts:
        current=current/part
        if current.is_symlink():raise HTTPException(409,'原生资源不允许链接')


def visible(row,sid):
    if row.get('sessionId')!=sid or row.get('isSidechain'):return None
    role=row.get('type')
    if role not in ('user','assistant'):return None
    message=row.get('message') or {}
    if not isinstance(message,dict):return None
    content=message.get('content',[])
    if isinstance(content,str):content=[{'type':'text','text':content}]
    texts=[];tools=[];images=0
    for block in content if isinstance(content,list) else []:
        if not isinstance(block,dict):continue
        if block.get('type')=='text' and isinstance(block.get('text'),str):
            text=block['text']
            if role=='user':
                try:envelope=json.loads(text)
                except ValueError:envelope=None
                fields={'history','associated_paper_ids','selected_contexts','import_request_id','current_user_message'}
                if isinstance(envelope,dict) and set(envelope)==fields and isinstance(envelope['current_user_message'],str):text=envelope['current_user_message']
            texts.append(text[:48000])
        elif block.get('type')=='tool_use':tools.append(str(block.get('name',''))[:160])
        elif block.get('type')=='image':images+=1
    if not texts and not tools and not images:return None
    return {'id':str(row.get('uuid',''))[:100],'role':role,'text':'\n'.join(texts)[:48000],'truncated':sum(len(b.get('text','')) for b in content if isinstance(b,dict) and b.get('type')=='text' and isinstance(b.get('text'),str))>48000,'tools':tools[:30],'images':images,'timestamp':str(row.get('timestamp',''))[:60]}


def transcript(runtime,conversation_id,offset=0,source=None,limit=50,allow_legacy=False):
    runtime=Path(runtime);sid,config=binding(runtime,conversation_id,allow_legacy)
    safe_path(config,runtime)
    projects=config/'projects';safe_path(projects,runtime)
    files=[]
    if projects.is_dir():
        # Only exact session file names below the selected configuration root.
        for i,folder in enumerate(projects.iterdir()):
            if i>=2000:raise HTTPException(409,'原生项目目录过多，请联系维护者')
            candidate=folder/(sid+'.jsonl')
            if candidate.exists():
                safe_path(candidate,runtime)
                if candidate.is_file():files.append(candidate)
    if len(files)>1:raise HTTPException(409,'原生会话文件冲突，拒绝猜测来源')
    if not files:return {'session_id':sid,'state':'not_found','events':[],'next_offset':0,'source':None,'has_more':False,'reset':False}
    path=files[0]
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode):raise HTTPException(409,'原生会话资源无效')
        generation=hashlib.sha256(f'{sid}:{info.st_dev}:{info.st_ino}'.encode()).hexdigest()[:32]
        reset=bool(source and source!=generation) or offset>info.st_size
        if reset:offset=0
        if offset and not source:raise HTTPException(422,'继续读取需要来源标识')
        f.seek(offset)
        if offset:
            f.seek(offset-1)
            if f.read(1)!=b'\n':raise HTTPException(422,'原生会话游标无效')
        events=[];scanned=0;skipped=0
        while len(events)<limit and scanned<MAX_SCAN:
            start=f.tell();line=f.readline(MAX_LINE+1)
            if not line:break
            scanned+=len(line)
            if not line.endswith(b'\n'):
                if len(line)<=MAX_LINE:
                    f.seek(start);break  # An in-flight JSON record is not yet committed.
                raise HTTPException(413,'原生日志含超大记录，请查看平台完整会话')
            try:row=json.loads(line)
            except (ValueError,UnicodeDecodeError):skipped+=1;continue
            if not isinstance(row,dict):skipped+=1;continue
            item=visible(row,sid)
            if item:events.append(item)
        end=f.tell()
        return {'session_id':sid,'state':'available','events':events,'next_offset':end,'source':generation,'has_more':end<info.st_size,'reset':reset,'skipped_records':skipped}


async def provider_status():
    """Probe the exact managed executable without authentication or model requests."""
    import asyncio
    import time
    global _provider_cache
    if _provider_cache and time.monotonic()-_provider_cache[0]<60:return _provider_cache[1]
    from .cli import binary_path
    executable=binary_path()
    result={'id':'claude_code','name':'Claude Code','installed':executable.is_file(),'version':None,'authentication':'not_checked','execution':'managed_print','capabilities':{'native_history':True,'structured_stream':False,'terminal':False,'permission_reply':False},'status':'missing'}
    if result['installed']:
        proc=None
        try:
            env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','LC_ALL')}
            proc=await asyncio.create_subprocess_exec(str(executable),'--version',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env)
            out,_=await asyncio.wait_for(proc.communicate(),3)
            version=re.search(r'\b\d+\.\d+\.\d+\b',out.decode(errors='replace')[:1000])
            result.update(version=version.group() if version else None,status='installed' if proc.returncode==0 else 'probe_failed')
            proc=await asyncio.create_subprocess_exec(str(executable),'--help',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env)
            help_out,_=await asyncio.wait_for(proc.communicate(),3)
            result['capabilities']['structured_stream']=proc.returncode==0 and b'--include-partial-messages' in help_out and b'stream-json' in help_out
        except (OSError,asyncio.TimeoutError):
            if proc and proc.returncode is None:
                proc.kill();await proc.wait()
            result['status']='probe_failed'
    _provider_cache=(time.monotonic(),result)
    return result


_provider_cache=None
