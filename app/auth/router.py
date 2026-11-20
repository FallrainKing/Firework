"""Session login, closed registration, and metadata-only account administration."""
import asyncio
import hmac
import sqlite3
import time
import uuid
from fastapi import APIRouter,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from ..core.errors import ServiceError
from .store import COOKIE,username,new_password,password_hash,verify_password

router=APIRouter(tags=['authentication'])
_hash_slots=asyncio.Semaphore(4)

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Login(Strict):
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=256)
class AccountCreate(Login):pass
class AccountPatch(Strict):
    enabled:bool
class PasswordChange(Strict):
    current_password:str=Field(min_length=1,max_length=256)
    new_password:str=Field(min_length=12,max_length=256)
class PasswordReset(Strict):
    new_password:str=Field(min_length=12,max_length=256)

async def hash_async(value):
    async with _hash_slots:return await asyncio.to_thread(password_hash,value)

async def verify_async(value,encoded):
    async with _hash_slots:return await asyncio.to_thread(verify_password,value,encoded)

def store(request):return request.app.state.auth_store

def identity(request):
    got=getattr(request.state,'auth_user',None)
    if not got:raise ServiceError(401,'请先登录')
    return got

def view(a,s):
    return {**s.public(a),'login_allowed':s.login_allowed(a)}

@router.get('/api/auth/session')
async def session(request:Request):
    s=store(request);a=s.session(request.cookies.get(s.cookie_name,''))
    return {'authenticated':bool(a),'account':view(a,s) if a else None,'csrf_token':a['csrf'] if a else None,
            'registration_open':False,'admin_only':s.admin_only,'initialized':bool(s.primary_id()),
            'secure_cookie':s.secure_cookie,'login_url':s.public_origin+'/#/login'}

@router.post('/api/auth/login')
async def login(body:Login,request:Request,response:Response):
    s=store(request);name=body.username.strip().casefold()
    if not s.throttle(name,request.client.host if request.client else 'unknown'):
        raise ServiceError(429,'登录尝试过多，请稍后重试')
    a=s.by_username(name)
    ok=await verify_async(body.password,a['password_hash'] if a else s.dummy_hash)
    current=s.account(a['id']) if a else None
    if not ok or not s.login_allowed(current) or current['password_hash']!=a['password_hash']:
        s.audit(None,'login-rejected',a['id'] if a else None);s.db.commit()
        raise ServiceError(401,'账号或密码错误，或账号暂未开放登录')
    # Successful login rotates any previous browser session.
    if request.cookies.get(s.cookie_name):s.revoke(request.cookies[s.cookie_name])
    token,csrf=s.issue_session(current)
    s.clear_name_throttle(name)
    response.set_cookie(s.cookie_name,token,max_age=43200,secure=s.secure_cookie,httponly=True,samesite='strict',path='/')
    return {'authenticated':True,'account':view(current,s),'csrf_token':csrf,'registration_open':False,'admin_only':s.admin_only}

@router.post('/api/auth/register')
async def register(request:Request):
    raise ServiceError(403,'公开注册暂未开放，请联系管理员')

@router.post('/api/auth/logout')
async def logout(request:Request,response:Response):
    a=identity(request);s=store(request);s.revoke(request.cookies.get(s.cookie_name,''))
    s.audit(a['id'],'logout',a['id']);s.db.commit()
    response.delete_cookie(s.cookie_name,path='/',secure=s.secure_cookie,httponly=True,samesite='strict')
    return {'saved':True}

@router.post('/api/auth/password')
async def change_password(body:PasswordChange,request:Request,response:Response):
    a=identity(request);s=store(request)
    if not s.throttle('password:'+a['id'],request.client.host if request.client else 'unknown'):
        raise ServiceError(429,'操作过于频繁，请稍后重试')
    if not await verify_async(body.current_password,a['password_hash']):raise ServiceError(400,'当前密码不正确')
    encoded=await hash_async(new_password(body.new_password))
    cur=s.db.execute('UPDATE accounts SET password_hash=?,session_version=session_version+1 WHERE id=? AND session_version=?',(encoded,a['id'],a['session_version']))
    if cur.rowcount!=1:s.db.rollback();raise ServiceError(409,'账号状态已变化，请重新登录')
    s.audit(a['id'],'password-change',a['id']);s.db.commit()
    response.delete_cookie(s.cookie_name,path='/',secure=s.secure_cookie,httponly=True,samesite='strict')
    return {'saved':True,'reauthenticate':True}

@router.get('/api/admin/accounts')
async def accounts(request:Request):
    s=store(request);identity(request)
    return {'accounts':[view(dict(a),s) for a in s.db.execute('SELECT * FROM accounts ORDER BY created_at,id')],
            'registration_open':False,'admin_only':s.admin_only}

@router.post('/api/admin/accounts',status_code=201)
async def create_account(body:AccountCreate,request:Request):
    actor=identity(request);s=store(request)
    try:name=username(body.username);new_password(body.password)
    except ValueError as e:raise ServiceError(422,str(e)) from e
    if s.by_username(name):raise ServiceError(409,'账号已存在')
    encoded=await hash_async(body.password)
    ident=uuid.uuid4().hex;key=uuid.uuid4().hex
    request.app.state.workspaces.provision(key,name)
    try:
        s.db.execute("INSERT INTO accounts(id,username,password_hash,role,enabled,workspace_key,created_at) VALUES (?,?,?,'user',0,?,?)",(ident,name,encoded,key,int(time.time())))
        s.audit(actor['id'],'account-created',ident);s.db.commit()
    except sqlite3.IntegrityError:s.db.rollback();raise ServiceError(409,'账号已存在') from None
    return view(s.account(ident),s)

@router.patch('/api/admin/accounts/{ident}')
async def update_account(ident:str,body:AccountPatch,request:Request):
    actor=identity(request);s=store(request);a=s.account(ident)
    if not a:raise ServiceError(404,'账号不存在')
    if ident==s.primary_id():raise ServiceError(409,'不能停用当前管理员')
    s.db.execute('UPDATE accounts SET enabled=?,session_version=session_version+1 WHERE id=?',(body.enabled,ident))
    s.audit(actor['id'],'account-enabled' if body.enabled else 'account-disabled',ident);s.db.commit()
    if not body.enabled:await request.app.state.workspaces.stop_account(a['workspace_key'])
    return view(s.account(ident),s)

@router.post('/api/admin/accounts/{ident}/password')
async def reset_password(ident:str,body:PasswordReset,request:Request):
    actor=identity(request);s=store(request);a=s.account(ident)
    if not a:raise ServiceError(404,'账号不存在')
    if ident==s.primary_id():raise ServiceError(409,'请在账号安全中验证当前密码后修改管理员密码')
    encoded=await hash_async(new_password(body.new_password))
    s.db.execute('UPDATE accounts SET password_hash=?,session_version=session_version+1 WHERE id=?',(encoded,ident))
    s.audit(actor['id'],'account-password-reset',ident);s.db.commit()
    await request.app.state.workspaces.stop_account(a['workspace_key'])
    return {'saved':True}
