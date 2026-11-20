"""Browser-approved, revocable devices. No browser passwords in plugins."""
import secrets,time,uuid
from ...auth.store import token_hash
from ...core.errors import ServiceError


def begin(store,name,instance):
    ident=uuid.uuid4().hex;secret=secrets.token_urlsafe(32);code=secrets.token_hex(4).upper()
    store.db.execute('DELETE FROM zotero_pairings WHERE expires_at<?',(int(time.time()),))
    store.db.execute('INSERT INTO zotero_pairings(id,secret_hash,user_code,name,instance_id,expires_at) VALUES (?,?,?,?,?,?)',(ident,token_hash(secret),code,name,instance,int(time.time())+600));store.db.commit()
    return {'pair_id':ident,'device_code':secret,'user_code':code,'verification_url':store.public_origin+'/integrations/zotero','expires_in':600}


def approve(store,code,account):
    row=store.db.execute('SELECT * FROM zotero_pairings WHERE user_code=? AND expires_at>? AND claimed=0',(code.upper().strip(),int(time.time()))).fetchone()
    if not row:raise ServiceError(404,'配对码不存在或已过期')
    if row['account_id'] and row['account_id']!=account['id']:raise ServiceError(409,'配对请求已绑定其他账号')
    store.db.execute('UPDATE zotero_pairings SET account_id=? WHERE id=?',(account['id'],row['id']));store.db.commit()
    store.audit(account['id'],'zotero-pair-approved',row['id']);store.db.commit()
    return {'approved':True,'device_name':row['name']}


def claim(store,ident,secret):
    row=store.db.execute('SELECT * FROM zotero_pairings WHERE id=? AND secret_hash=? AND expires_at>? AND claimed=0',(ident,token_hash(secret),int(time.time()))).fetchone()
    if not row:raise ServiceError(404,'配对请求无效、已领取或已过期')
    if not row['account_id']:return {'status':'pending'}
    a=store.account(row['account_id'])
    if not store.login_allowed(a):raise ServiceError(403,'账号不可用')
    existing=store.db.execute('SELECT id FROM zotero_devices WHERE account_id=? AND instance_id=?',(a['id'],row['instance_id'])).fetchone()
    device=existing['id'] if existing else uuid.uuid4().hex;token=secrets.token_urlsafe(48);now=int(time.time())
    with store.db:
        store.db.execute('INSERT INTO zotero_devices(id,account_id,name,instance_id,token_hash,session_version,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET token_hash=excluded.token_hash,session_version=excluded.session_version,expires_at=excluded.expires_at,revoked=0',(device,a['id'],row['name'],row['instance_id'],token_hash(token),a['session_version'],now,now+30*86400))
        store.db.execute('UPDATE zotero_pairings SET claimed=1 WHERE id=?',(ident,))
    return {'status':'approved','device_id':device,'token':token,'expires_in':30*86400}


def principal(store,token):
    row=store.db.execute('SELECT * FROM zotero_devices WHERE token_hash=? AND revoked=0 AND expires_at>?',(token_hash(token),int(time.time()))).fetchone()
    if not row:return None
    a=store.account(row['account_id'])
    if not store.login_allowed(a) or a['session_version']!=row['session_version']:return None
    return {**a,'zotero_device_id':row['id']}
