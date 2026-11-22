import json
import secrets
import time
import uuid
from pydantic import BaseModel,ConfigDict,Field
from ..auth.store import token_hash
from ..core.errors import ServiceError
SCOPES={'papers:read','papers:write','annotations:read','annotations:write','files:read','frontier:read','frontier:write'}
class TokenCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=80)
    scopes:list[str]=Field(min_length=1,max_length=7)
    paper_ids:list[int]|None=Field(None,max_length=200)
    expires_days:int=Field(7,ge=1,le=90)

def listing(store,account):
    return {'tokens':[{'id':r['id'],'name':r['name'],'prefix':r['prefix'],'scopes':json.loads(r['scopes_json']),'paper_ids':json.loads(r['paper_ids_json']) if r['paper_ids_json'] else None,'expires_at':r['expires_at'],'revoked':bool(r['revoked']),'last_seen':r['last_seen']} for r in store.db.execute('SELECT * FROM external_tokens WHERE account_id=? ORDER BY created_at DESC',(account['id'],))]}

def create(store,account,db,body):
    if not body.name.strip() or not set(body.scopes)<=SCOPES:raise ServiceError(422,'名称或 scope 无效')
    if body.paper_ids is not None and set(body.scopes)&{'frontier:read','frontier:write'}:raise ServiceError(422,'前沿权限需要不限定论文的独立授权')
    if body.paper_ids is not None:
        if not body.paper_ids or any(not db.execute('SELECT 1 FROM papers WHERE id=?',(pid,)).fetchone() for pid in body.paper_ids):raise ServiceError(422,'论文授权列表无效')
    ident=uuid.uuid4().hex;token='fw_'+secrets.token_urlsafe(32);now=int(time.time())
    with store.db:
        store.db.execute('INSERT INTO external_tokens(id,account_id,name,token_hash,prefix,scopes_json,paper_ids_json,session_version,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,account['id'],body.name.strip(),token_hash(token),token[:10],json.dumps(sorted(set(body.scopes))),json.dumps(sorted(set(body.paper_ids))) if body.paper_ids is not None else None,account['session_version'],now,now+body.expires_days*86400))
        store.audit(account['id'],'external-token.create',ident)
    return {'id':ident,'token':token,'expires_at':now+body.expires_days*86400,'show_once':True}

def revoke(store,account,ident):
    with store.db:
        cur=store.db.execute('UPDATE external_tokens SET revoked=1 WHERE id=? AND account_id=?',(ident,account['id']))
        if not cur.rowcount:raise ServiceError(404,'授权不存在')
        store.audit(account['id'],'external-token.revoke',ident)
    return {'revoked':True}

def principal(store,raw):
    if not raw.startswith('fw_') or len(raw)>100:return None
    row=store.db.execute('SELECT * FROM external_tokens WHERE token_hash=?',(token_hash(raw),)).fetchone()
    if not row or row['revoked'] or row['expires_at']<=int(time.time()):return None
    account=store.account(row['account_id'])
    if not store.login_allowed(account) or account['session_version']!=row['session_version']:return None
    window=int(time.time())//60
    with store.db:
        cur=store.db.execute('UPDATE external_tokens SET rate_count=CASE WHEN rate_window=? THEN rate_count+1 ELSE 1 END,rate_window=?,last_seen=? WHERE id=? AND (rate_window<>? OR rate_count<60)',(window,window,int(time.time()),row['id'],window))
        if not cur.rowcount:raise ServiceError(429,'外部授权每分钟最多 60 次请求')
    return account,dict(row)

def require(request,scope,pid=None):
    token=getattr(request.state,'external_token',None)
    if token is None or scope not in json.loads(token['scopes_json']):raise ServiceError(403,'外部授权缺少所需 scope')
    allowed=json.loads(token['paper_ids_json']) if token['paper_ids_json'] else None
    if allowed is not None and (pid is None or pid not in allowed):raise ServiceError(404,'论文未授权或不存在')
    return token
