import json,time
from typing import Literal
from fastapi import APIRouter,Request,File,Form,UploadFile
from fastapi.responses import FileResponse
from ...auth.router import identity
from ...core.errors import ServiceError
from ...documents import service as documents
from . import auth,service as s
from .schemas import PairStart,PairClaim,Approval,ImportItem,ExportRequest,Ack,AttachmentCheck

router=APIRouter(prefix='/api/zotero',tags=['zotero'])

def device(request):
    actor=identity(request);ident=actor.get('zotero_device_id')
    if not ident:raise ServiceError(403,'此接口仅供已配对的 Zotero 插件使用')
    row=request.app.state.auth_store.db.execute('SELECT * FROM zotero_devices WHERE id=?',(ident,)).fetchone()
    return dict(row)

def owned(request,ident):
    a=identity(request)
    r=request.app.state.auth_store.db.execute('SELECT * FROM zotero_devices WHERE id=? AND account_id=?',(ident,a['id'])).fetchone()
    if not r:raise ServiceError(404,'设备不存在')
    return r

@router.post('/pair/start')
async def pair_start(body:PairStart,request:Request):
    store=request.app.state.auth_store
    if not store.throttle('zotero-pair',request.client.host if request.client else 'unknown'):raise ServiceError(429,'配对请求过于频繁')
    return auth.begin(store,body.name,body.instance_id)

@router.post('/pair/claim')
async def pair_claim(body:PairClaim,request:Request):return auth.claim(request.app.state.auth_store,body.pair_id,body.device_code)

@router.post('/pair/inspect')
async def inspect(body:Approval,request:Request):
    a=identity(request);store=request.app.state.auth_store
    r=store.db.execute('SELECT name,instance_id,expires_at,account_id FROM zotero_pairings WHERE user_code=? AND expires_at>? AND claimed=0',(body.user_code.upper(),int(time.time()))).fetchone()
    if not r or (r['account_id'] and r['account_id']!=a['id']):raise ServiceError(404,'配对码不存在或过期')
    return {k:r[k] for k in ('name','instance_id','expires_at')}

@router.post('/pair/approve')
async def approve(body:Approval,request:Request):return auth.approve(request.app.state.auth_store,body.user_code,identity(request))

@router.get('/devices')
async def devices(request:Request):
    a=identity(request)
    return {'devices':[dict(r) for r in request.app.state.auth_store.db.execute('SELECT id,name,instance_id,created_at,expires_at,revoked FROM zotero_devices WHERE account_id=? ORDER BY created_at DESC',(a['id'],))]}

@router.delete('/devices/{ident}')
async def revoke(ident:str,request:Request):
    owned(request,ident);store=request.app.state.auth_store
    store.db.execute('UPDATE zotero_devices SET revoked=1 WHERE id=?',(ident,));store.audit(identity(request)['id'],'zotero-device-revoked',ident);store.db.commit()
    return {'revoked':True}

@router.post('/exports')
async def exports(body:ExportRequest,request:Request):
    d=owned(request,body.device_id)
    if d['revoked'] or d['expires_at']<=int(time.time()):raise ServiceError(409,'设备已撤销或过期')
    state=request.app.state
    for pid in body.paper_ids:s.require_paper(state.db,pid)
    return {'jobs':[s.enqueue(state.db,state.settings,body.device_id,pid,body.request_key+':'+str(pid)) for pid in dict.fromkeys(body.paper_ids)]}

@router.get('/exports')
async def export_list(request:Request):
    return {'jobs':[dict(r) for r in request.app.state.db.execute('SELECT id,device_id,paper_id,status,error,created_at FROM zotero_exports ORDER BY created_at DESC LIMIT 100')]}

@router.post('/exports/{ident}/retry')
async def retry(ident:str,request:Request):
    db=request.app.state.db
    r=db.execute('SELECT * FROM zotero_exports WHERE id=?',(ident,)).fetchone()
    if not r:raise ServiceError(404,'任务不存在')
    if r['status']!='failed':raise ServiceError(409,'仅失败任务可重试')
    d=owned(request,r['device_id'])
    if d['revoked']:raise ServiceError(409,'设备已撤销')
    db.execute("UPDATE zotero_exports SET status='pending',error=NULL,lease_token=NULL WHERE id=?",(ident,));db.commit()
    return {'saved':True}

@router.post('/device/items')
async def import_item(body:ImportItem,request:Request):return s.import_item(request.app.state.db,device(request),body)

@router.post('/device/papers/{pid}/attachments')
async def upload(pid:int,request:Request,file:UploadFile=File(...),library_key:str=Form(...,max_length=80),item_key:str=Form(...,pattern=r'^[A-Z0-9]{8}$'),attachment_key:str=Form(...,pattern=r'^[A-Z0-9]{8}$'),label:str=Form(...,min_length=1,max_length=100),role:Literal['main','supplement']=Form('main')):
    d=device(request)
    data=await file.read(documents.MAX_BYTES+1)
    return await s.attachment(request.app.state,d['id'],pid,library_key,item_key,attachment_key,data,label,file.filename or 'paper.pdf',role)

@router.post('/device/exports/claim')
async def claim(request:Request):return s.claim_export(request.app.state.db,device(request)['id'])

@router.get('/device/exports/{ident}/files/{vid}')
async def file(ident:str,vid:str,request:Request):
    d=device(request);state=request.app.state
    r=s.export_job(state.db,d['id'],ident,request.headers.get('x-sync-lease',''))
    if not any(f['version_id']==vid for f in json.loads(r['payload_json'])['files']):raise ServiceError(404,'文件不在此次授权任务中')
    v=documents.version(state.db,r['paper_id'],vid)
    return FileResponse(documents.asset_path(state.settings,v['storage_key']),media_type='application/pdf')

@router.post('/device/exports/{ident}/ack')
async def ack(ident:str,body:Ack,request:Request):return s.acknowledge(request.app.state.db,device(request)['id'],ident,body)

@router.post('/device/papers/{pid}/attachments/check')
async def attachment_check(pid:int,body:AttachmentCheck,request:Request):
    d=device(request);state=request.app.state
    s.linked(state.db,d['id'],body.library_key,body.item_key,pid)
    old=state.db.execute('SELECT * FROM zotero_attachment_links WHERE device_id=? AND library_key=? AND attachment_key=? AND item_key=?',(d['id'],body.library_key,body.attachment_key,body.item_key)).fetchone()
    present=False
    if old and old['file_hash']==body.file_hash:
        v=documents.version(state.db,pid,old['version_id'])
        present=documents.asset_path(state.settings,v['storage_key']).is_file()
        if v['role']=='main' and not s.require_paper(state.db,pid)['default_version_id']:present=False
    return {'present':present}
