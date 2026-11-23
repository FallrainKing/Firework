"""Per-account Docker PTYs. The container has no network or host credentials."""
import asyncio
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import secrets
import sqlite3
import time
from fastapi import HTTPException
from . import cli,connections
from .model_bridge import ModelBridge
from app.research.events import append as event
from app.agent import repository as runs

IMAGE=os.getenv('FIREWORK_NATIVE_IMAGE','firework-native-runner:2.1.322')
MAX_OUTPUT=2*1024*1024


def database(runtime):
    db=sqlite3.connect(Path(runtime).parent/'app.db',timeout=10)
    db.row_factory=sqlite3.Row
    return db


def state(runtime,ident,status,error=None,generation=None):
    with database(runtime) as db:
        db.execute('UPDATE native_terminals SET state=?,error=?,generation=COALESCE(?,generation),updated_at=CURRENT_TIMESTAMP WHERE conversation_id=?',(status,error,generation,ident))


async def command(*args,timeout=10):
    proc=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:out,err=await asyncio.wait_for(proc.communicate(),timeout)
    except asyncio.TimeoutError:
        proc.kill();await proc.wait();raise ValueError('Container operation timed out') from None
    if proc.returncode:raise ValueError('Container operation failed')
    return out


async def availability():
    enabled=os.getenv('FIREWORK_NATIVE_ENABLED','0')=='1'
    result={'enabled':enabled,'available':False,'network':'model_only','permissions':'native_prompt','reason':None}
    if not enabled:return result|{'reason':'隔离终端尚未启用'}
    binary=cli.binary_path()
    expected=os.getenv('FIREWORK_NATIVE_CLI_SHA256','')
    if not re.fullmatch('[a-f0-9]{64}',expected) or not binary.is_file():return result|{'reason':'缺少固定版本CLI及校验值'}
    try:
        def checksum():
            with binary.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
        actual=await asyncio.to_thread(checksum)
        if actual!=expected:raise ValueError('CLI checksum mismatch')
        await command('docker','image','inspect',IMAGE)
    except (OSError,ValueError):return result|{'reason':'隔离镜像或CLI校验未通过'}
    return result|{'available':True}


def container_args(folder,name,sid,model,token,resume):
    folder=Path(folder).resolve()
    return ['docker','run','--rm','--name',name,'--label','firework.native=1','--network','none','--read-only','--cap-drop=ALL','--security-opt','no-new-privileges','--pids-limit','128','--memory','2g','--cpus','2','--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--interactive','--tty',
        '--mount',f'type=bind,src={folder / "workspace"},dst=/workspace',
        '--mount',f'type=bind,src={folder / "papers"},dst=/papers,readonly',
        '--mount',f'type=bind,src={folder / "config"},dst=/state',
        '--mount',f'type=bind,src={folder / "bridge"},dst=/bridge,readonly',
        '--mount',f'type=bind,src={cli.binary_path().resolve()},dst=/usr/local/bin/claude,readonly',
        '--env','HOME=/state','--env','CLAUDE_CONFIG_DIR=/state','--env','TERM=xterm-256color',
        '--env','DISABLE_AUTOUPDATER=1','--env','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1',
        '--env','ANTHROPIC_BASE_URL=http://127.0.0.1:8999','--env',f'ANTHROPIC_API_KEY={token}',
        '--env',f'ANTHROPIC_MODEL={model}',*sum((['--env',f'ANTHROPIC_DEFAULT_{tier}_MODEL={model}'] for tier in ('SONNET','OPUS','HAIKU','FABLE')),[]),'--env',f'CLAUDE_CODE_SUBAGENT_MODEL={model}','--env',f'FIREWORK_SESSION_ID={sid}','--env',f'FIREWORK_RESUME={int(resume)}',IMAGE]


class TerminalManager:
    def __init__(self,engine):
        self.engine=engine;self.runtime=engine.runtime;self.items={};self.lock=asyncio.Lock()
    def lookup(self,ident):
        with database(self.runtime) as db:
            row=db.execute('SELECT c.*,t.state AS terminal_state,t.generation,t.error FROM conversations c JOIN native_terminals t ON t.conversation_id=c.id WHERE c.id=?',(ident,)).fetchone()
        if not row:raise HTTPException(404,'Terminal session not found')
        if row['execution_mode']!='terminal':raise HTTPException(409,'Not a terminal session')
        return row
    async def recover(self):
        # Never replay a paid request after a Runner restart; clean up only recorded leases.
        if not (self.runtime.parent/'app.db').is_file():return
        try:
            with database(self.runtime) as db:rows=db.execute("SELECT conversation_id FROM native_terminals WHERE state IN ('starting','running')").fetchall()
        except sqlite3.OperationalError:return
        for row in rows:
            with contextlib.suppress(OSError,ValueError):await command('docker','rm','--force',self.name(row[0]),timeout=5)
            state(self.runtime,row[0],'failed','运行服务已重启；请明确恢复终端，不自动重发问题')
    def name(self,ident):
        key=hashlib.sha256(str(self.runtime.resolve()).encode()).hexdigest()[:12]
        return f'firework-native-{key}-{ident}'
    async def start(self,ident,body,primary):
        async with self.lock:
            row=self.lookup(ident)
            if row['archived']:raise HTTPException(409,'会话已归档')
            if ident in self.items and self.items[ident]['state']=='running':
                item=self.items[ident];owner=body['controller_id']
                if item['controller_id']!=owner and time.monotonic()-item['last_seen']<20:raise HTTPException(409,'另一个窗口正在控制，请先关闭该窗口或等待20秒')
                item['controller_id']=owner;item['last_seen']=time.monotonic();return self.read(ident)
            ready=await availability()
            if not ready['available']:raise HTTPException(503,ready['reason'])
            snap=json.loads(row['runner_connection_json'] or '{}')
            if snap.get('mode')=='custom':
                actual=body.get('connection_snapshot') or {}
                if actual!={k:v for k,v in snap.items() if k!='mode'}:raise HTTPException(409,'Connection binding mismatch')
                connections.check_current(self.runtime,actual)
                base=snap['base_url'];model=snap['model'];auth=snap['auth_type'];secret=body.get('connection_secret')
            else:
                if not primary:raise HTTPException(403,'Own model connection required')
                env=self.engine._env_loader(self.runtime)
                base=env.get('ANTHROPIC_BASE_URL','https://api.anthropic.com');model=cli.current_model(env)
                secret=env.get('ANTHROPIC_AUTH_TOKEN') or env.get('ANTHROPIC_API_KEY')
                auth='bearer' if env.get('ANTHROPIC_AUTH_TOKEN') else 'api_key'
            if not secret:raise HTTPException(409,'模型凭据不可用')
            try:await asyncio.wait_for(self.engine._sem.acquire(),.1)
            except asyncio.TimeoutError:raise HTTPException(429,'执行资源正在使用，请稍后重试') from None
            folder=self.runtime/'terminals'/str(ident)
            try:
                for name in ('workspace','papers','config','bridge'):
                    target=folder/name
                    if target.is_symlink() or folder.is_symlink():raise HTTPException(409,'Terminal directory links forbidden')
                    target.mkdir(parents=True,exist_ok=True,mode=0o700)
            except Exception:
                self.engine._sem.release();raise
            token=secrets.token_hex(32);generation=secrets.token_hex(16)
            relay=ModelBridge(folder/'bridge',base,secret,auth,model,token)
            def authorize():
                try:
                    with database(self.runtime) as db:
                        current=db.execute('SELECT archived,execution_mode FROM conversations WHERE id=?',(ident,)).fetchone()
                    if not current or current['archived'] or current['execution_mode']!='terminal':return False
                    if snap.get('mode')=='custom':connections.check_current(self.runtime,{k:v for k,v in snap.items() if k!='mode'})
                    data_root=self.runtime.parent if primary else self.runtime.parent.parent.parent
                    auth_db=data_root/'auth/accounts.db'
                    if auth_db.is_file():
                        with sqlite3.connect(auth_db.resolve().as_uri()+'?mode=ro',uri=True) as account_db:
                            account=account_db.execute('SELECT enabled FROM accounts WHERE workspace_key=?',('legacy' if primary else self.runtime.parent.name,)).fetchone()
                        if not account or not account[0]:return False
                    return True
                except (ValueError,OSError,sqlite3.Error):return False
            relay.authorize=authorize
            item={'state':'starting','output':bytearray(),'base':0,'generation':generation,'relay':relay,'folder':folder,'input_keys':{},'lock':asyncio.Lock(),'released':False,'proc':None,'fd':None,'controller_id':body['controller_id'],'last_seen':time.monotonic(),'run_id':secrets.token_hex(16)}
            self.items[ident]=item;state(self.runtime,ident,'starting',generation=generation)
            try:
                with database(self.runtime) as db:
                    runs.insert_run(db,item['run_id'],'terminal:'+generation,ident,'chat','原生隔离终端会话','[]','chat','[]',execution_policy_json=json.dumps({'mode':'native_terminal','network':'model_only','tools':['Read','Edit','Bash'],'connection_snapshot':{k:v for k,v in snap.items() if k not in ('role_prompt',)}}))
                    runs.set_run_status(db,item['run_id'],'running')
                    raw=json.loads((folder/'papers/manifest.json').read_text()) if (folder/'papers/manifest.json').is_file() else []
                    manifest=[{'paper_id':r['paper_id'],'document_version_id':r.get('document_version_id'),'file_version':r['sha256'],'storage_key':f'agent/terminals/{ident}/papers/'+r['file']} for r in raw]
                    db.execute('INSERT INTO material_manifests(run_id,authorized_json) VALUES (?,?)',(item['run_id'],json.dumps(manifest)))
                    event(db,item['run_id'],'native_started',{'session_id':ident,'network':'model_only'})
                await relay.start()
                sid=row['native_session_id'];resume=any((folder/'config/projects').glob('*/'+sid+'.jsonl'))
                master,slave=pty.openpty();item['fd']=master
                try:
                    item['proc']=await asyncio.create_subprocess_exec(*container_args(folder,self.name(ident),sid,model,token,resume),stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
                finally:os.close(slave)
                item['state']='running';state(self.runtime,ident,'running')
                item['pump']=asyncio.create_task(self.pump(ident,item))
                item['timer']=asyncio.create_task(self.expire(ident,item))
            except Exception:
                item['state']='failed';state(self.runtime,ident,'failed','隔离终端未能启动')
                try:await self.finish_run(ident,item,'failed','隔离终端未能启动')
                finally:await self.release(item)
                raise HTTPException(503,'隔离终端未能启动') from None
            return self.read(ident)
    async def expire(self,ident,item):
        deadline=time.monotonic()+max(60,min(int(os.getenv('FIREWORK_NATIVE_TTL_SECONDS','7200')),86400))
        reason=None
        while self.items.get(ident) is item and item['state']=='running':
            await asyncio.sleep(5)
            if not item['relay'].authorize():reason='账号、模型连接或会话授权已变化';break
            size=0;count=0
            for root,dirs,files in os.walk(item['folder']/'workspace',followlinks=False):
                for name in files:
                    with contextlib.suppress(OSError):size+=(Path(root)/name).lstat().st_size
                    count+=1
                if count>10000 or size>1024*1024*1024:reason='工作目录达到文件数量或空间保护阈值';break
            if reason:break
            if time.monotonic()>=deadline:reason='终端运行时限已到，请明确恢复';break
        if reason and self.items.get(ident) is item and item['state']=='running':await self.stop(ident,item['generation'],reason=reason)
    async def release(self,item):
        if item['released']:return
        item['released']=True
        if item['fd'] is not None:
            with contextlib.suppress(OSError):os.close(item['fd'])
        await item['relay'].close();self.engine._sem.release()
    async def pump(self,ident,item):
        try:
            while True:
                block=await asyncio.to_thread(os.read,item['fd'],65536)
                if not block:break
                item['output'].extend(block)
                if len(item['output'])>MAX_OUTPUT:
                    excess=len(item['output'])-MAX_OUTPUT;del item['output'][:excess];item['base']+=excess
        except (OSError,asyncio.CancelledError):pass
        finally:
            code=await item['proc'].wait()
            if item['state']=='running':
                item['state']='stopped' if code==0 else 'failed'
                state(self.runtime,ident,item['state'],None if code==0 else '终端已退出，请检查记录')
            await self.finish_run(ident,item,'succeeded' if item['state']=='stopped' and code==0 else 'failed',None if code==0 else '终端进程已退出')
            await self.release(item)
    async def finish_run(self,ident,item,status,error):
        answer=''
        with contextlib.suppress(Exception):
            from .native import transcript
            data=transcript(self.runtime,ident,limit=100,allow_legacy=True)
            answer='\n\n'.join(e['text'] for e in data['events'] if e['role']=='assistant')[-256000:]
        with database(self.runtime) as db:
            r=runs.find_run(db,item['run_id'])
            if not r or r['status'] not in ('queued','running'):return
            runs.finish_run(db,item['run_id'],status,answer,item['relay'].model,'{}','[]',json.dumps({'execution_mode':'native_terminal','native_session_id':self.lookup(ident)['native_session_id']}),None,error)
            event(db,item['run_id'],'finished',{'status':status,'error':error})
            if answer:db.execute('UPDATE conversations SET native_ready=1 WHERE id=?',(ident,))
    def read(self,ident,offset=0,generation=None,controller_id=None):
        row=self.lookup(ident);item=self.items.get(ident)
        if not item:return {'conversation_id':ident,'state':row['terminal_state'],'generation':row['generation'],'error':row['error'],'data':'','next_offset':0,'reset':bool(offset)}
        if controller_id==item['controller_id']:item['last_seen']=time.monotonic()
        end=item['base']+len(item['output'])
        reset=(generation is not None and generation!=item['generation']) or offset<item['base'] or offset>end
        if reset:offset=item['base']
        begin=max(0,offset-item['base']);chunk=bytes(item['output'][begin:begin+65536]);next_offset=item['base']+begin+len(chunk)
        return {'conversation_id':ident,'state':item['state'],'generation':item['generation'],'error':row['error'],'data':base64.b64encode(chunk).decode(),'next_offset':next_offset,'reset':reset,'run_id':item['run_id'],'model_requests':item['relay'].message_calls}
    def active(self,ident,generation,controller_id=None):
        self.lookup(ident);item=self.items.get(ident)
        if not item or item['state']!='running' or item['generation']!=generation:raise HTTPException(409,'终端已停止或来源已变化，请重新连接')
        if controller_id is not None and controller_id!=item['controller_id']:raise HTTPException(409,'终端控制已转移到其他窗口')
        return item
    async def input(self,ident,body):
        item=self.active(ident,body['generation'],body['controller_id']);text=body['data'];key=body['request_key'];digest=hashlib.sha256(text.encode()).hexdigest()
        async with item['lock']:
            if key in item['input_keys']:
                if item['input_keys'][key]!=digest:raise HTTPException(409,'Input request conflict')
                return {'accepted':True,'reused':True}
            item['relay'].armed=True
            def write_all():
                pending=text.encode()
                while pending:pending=pending[os.write(item['fd'],pending):]
            await asyncio.to_thread(write_all)
            item['last_seen']=time.monotonic()
            with database(self.runtime) as db:event(db,item['run_id'],'native_input',{'bytes':len(text.encode()),'request_key':key,'sha256':digest})
            item['input_keys'][key]=digest
            if len(item['input_keys'])>256:del item['input_keys'][next(iter(item['input_keys']))]
        return {'accepted':True}
    async def resize(self,ident,body):
        self.active(ident,body['generation'],body['controller_id'])
        try:await command('docker','container','resize','--height',str(body['rows']),'--width',str(body['cols']),self.name(ident),timeout=3)
        except (OSError,ValueError):raise HTTPException(409,'终端尺寸调整失败') from None
        return {'resized':True}
    async def stop(self,ident,generation,reason=None,controller_id=None):
        item=self.active(ident,generation,controller_id);item['state']='stopped'
        await self.finish_run(ident,item,'cancelled',reason or '用户停止终端')
        state(self.runtime,ident,'stopped',reason)
        with contextlib.suppress(OSError,ValueError):await command('docker','stop','--time','1',self.name(ident),timeout=5)
        if item['proc'] and item['proc'].returncode is None:await cli.stop_process(item['proc'])
        if 'timer' in item and item['timer'] is not asyncio.current_task():item['timer'].cancel()
        await self.release(item)
        return self.read(ident)
    def for_run(self,run_id):
        return next(((ident,item) for ident,item in self.items.items() if item['run_id']==run_id),None)
    async def close(self):
        for ident,item in list(self.items.items()):
            if item['state']=='running':
                with contextlib.suppress(Exception):await self.stop(ident,item['generation'],reason='运行服务已停止，请明确恢复')
