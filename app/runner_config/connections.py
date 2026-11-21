"""Account-local connections. Only the Web service decrypts credentials."""
import base64
import json
import os
import uuid
from pathlib import Path
from app.core.errors import ServiceError
from .connection_schemas import ConnectionSnapshot

def _cipher(settings,create=False):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    override=os.getenv('FIREWORK_RUNNER_MASTER_KEY_FILE')
    path=Path(override) if override else settings.data_dir/'auth/runner-master.key'
    if override and not path.is_file():raise ServiceError(503,'Runner 主密钥文件不可用')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not path.exists() and create:
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:pass
        else:
            with os.fdopen(fd,'wb') as f:f.write(AESGCM.generate_key(bit_length=256))
    try:
        key=path.read_bytes()
        if len(key)!=32:raise ValueError()
        return AESGCM(key)
    except (OSError,ValueError):raise ServiceError(503,'Runner 主密钥不可用，请恢复原密钥文件') from None

def _aad(settings,ident):return (getattr(settings,'workspace_key','legacy')+':'+ident).encode()
def encrypt(settings,ident,secret):
    nonce=os.urandom(12)
    return base64.urlsafe_b64encode(nonce+_cipher(settings,create=True).encrypt(nonce,secret.encode(),_aad(settings,ident))).decode()
def decrypt(settings,ident,raw):
    try:
        data=base64.urlsafe_b64decode(raw)
        return _cipher(settings).decrypt(data[:12],data[12:],_aad(settings,ident)).decode()
    except ServiceError:raise
    except Exception:raise ServiceError(503,'凭据无法解密，请恢复主密钥或重新保存 API Key') from None

def view(row):
    return {k:row[k] for k in ('id','name','revision','updated_at')}|{'enabled':bool(row['enabled']),'config':json.loads(row['config_json']),'has_credential':bool(row['secret_cipher']),'verification':'not_tested'}
def listing(db,settings):
    row=db.execute('SELECT * FROM runner_connection_settings WHERE id=1').fetchone()
    return {'connections':[view(r) for r in db.execute('SELECT * FROM runner_connections ORDER BY rowid')],
            'default_connection_id':row['default_connection_id'],'settings_revision':row['revision'],
            'legacy_available':getattr(settings,'workspace_key','legacy')=='legacy'}
def save(db,settings,body,ident=None):
    name=body.name.strip()
    if not name:raise ServiceError(422,'连接名称不能为空')
    old=db.execute('SELECT * FROM runner_connections WHERE id=?',(ident,)).fetchone() if ident else None
    if ident and not old:raise ServiceError(404,'连接不存在')
    if old and old['revision']!=body.expected_revision:raise ServiceError(409,'连接已更新，请重新载入')
    secret=body.api_key.get_secret_value() if body.api_key is not None else None
    if secret is not None and (not secret.strip() or len(secret)>4096 or any(ord(c)<32 for c in secret)):
        raise ServiceError(422,'API Key 必须是非空的单行文本，最长 4096 字符')
    if old and secret is None:
        previous=json.loads(old['config_json'])
        if any(previous[k]!=body.config.model_dump()[k] for k in ('base_url','auth_type')):
            raise ServiceError(422,'更改 API 地址或鉴权方式时请重新填写 API Key')
    if not old and not secret:raise ServiceError(422,'新连接需要 API Key；复制连接不会复制凭据')
    ident=ident or uuid.uuid4().hex
    cipher=encrypt(settings,ident,secret) if secret is not None else old['secret_cipher']
    with db:
        if old:
            cur=db.execute('UPDATE runner_connections SET name=?,config_json=?,secret_cipher=?,enabled=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?',
                (name,body.config.model_dump_json(),cipher,int(body.enabled),ident,body.expected_revision))
            if cur.rowcount!=1:raise ServiceError(409,'连接已更新，请重新载入')
        else:db.execute('INSERT INTO runner_connections(id,name,config_json,secret_cipher,enabled) VALUES (?,?,?,?,?)',(ident,name,body.config.model_dump_json(),cipher,int(body.enabled)))
    return view(db.execute('SELECT * FROM runner_connections WHERE id=?',(ident,)).fetchone())

def set_default(db,settings,body):
    if body.connection_id:
        row=db.execute('SELECT * FROM runner_connections WHERE id=?',(body.connection_id,)).fetchone()
        if not row or not row['enabled']:raise ServiceError(409,'连接不存在或已停用')
    elif getattr(settings,'workspace_key','legacy')!='legacy':
        raise ServiceError(409,'独立账号必须配置自己的连接，不可使用宿主机凭据')
    with db:
        cur=db.execute('UPDATE runner_connection_settings SET default_connection_id=?,revision=revision+1 WHERE id=1 AND revision=?',(body.connection_id,body.expected_revision))
        if cur.rowcount!=1:raise ServiceError(409,'默认配置已更新，请重新载入')
    return listing(db,settings)

def snapshot(db,settings,ref=None,bound=None):
    # Existing sessions stay bound even after account defaults change.
    binding=json.loads(bound) if bound else None
    if ref:ident=ref.id;revision=ref.revision
    elif binding and binding.get('mode')=='custom':ident=binding['id'];revision=binding['revision']
    elif binding:ident=None;revision=None
    else:ident=db.execute('SELECT default_connection_id FROM runner_connection_settings WHERE id=1').fetchone()[0];revision=None
    if not ident:
        if getattr(settings,'workspace_key','legacy')!='legacy':raise ServiceError(409,'请先在模型连接页配置自己的 API 连接')
        result={'mode':'legacy'}
    else:
        row=db.execute('SELECT * FROM runner_connections WHERE id=?',(ident,)).fetchone()
        if not row or not row['enabled']:raise ServiceError(409,'连接不存在或已停用')
        if revision and revision!=row['revision']:raise ServiceError(409,'会话绑定的连接已更新，请新建会话后使用新配置')
        result=ConnectionSnapshot(id=ident,revision=row['revision'],name=row['name'],**json.loads(row['config_json'])).model_dump()|{'mode':'custom'}
    if binding and binding!=result:raise ServiceError(409,'会话已绑定其他连接；请新建会话，避免将历史内容发往新服务商')
    return result

def materialize(db,settings,snap):
    if not snap or snap.get('mode')=='legacy':return None
    row=db.execute('SELECT * FROM runner_connections WHERE id=?',(snap['id'],)).fetchone()
    if not row or not row['enabled'] or row['revision']!=snap['revision']:raise ServiceError(409,'连接已停用或修订，任务没有调用模型，请重新创建会话')
    return decrypt(settings,row['id'],row['secret_cipher'])
