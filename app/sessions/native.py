"""Authenticated facade for account-bound native history and diagnostics."""
import json
import re
import httpx
from ..agent import runner_client
from ..core.errors import ServiceError
from .service import require_session
from ..runner_config import connections


def clean(text,secrets):
    for secret in secrets:
        if secret:text=text.replace(secret,'[REDACTED]')
    text=re.sub(r'(?i)((?:authorization\s*[:=]\s*bearer|(?:api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=])\s*)[^\s,;"\']+',r'\1[REDACTED]',text)
    return text


async def view(state,ident,offset,source,limit):
    session=require_session(state.db,ident)
    snap=json.loads(session['runner_connection_json'] or '{}')
    secrets=[]
    # Redact all currently stored account credentials, including disabled connections.
    for row in state.db.execute('SELECT id,secret_cipher FROM runner_connections'):
        try:secrets.append(connections.decrypt(state.settings,row['id'],row['secret_cipher']))
        except ServiceError:raise ServiceError(503,'无法核验凭据脱敏，暂不提供原生历史') from None
    try:
        async with runner_client.client() as client:
            response=await client.get(f'/native/sessions/{ident}',params={'offset':offset,'limit':limit,**({'source':source} if source else {})},timeout=10)
        if response.status_code!=200:
            if response.status_code in (404,409,413,422):
                raise ServiceError(response.status_code,'原生记录不可读取：'+str(response.json().get('detail',''))[:180])
            raise ServiceError(503,'运行服务暂不支持原生记录，请升级或检查运行服务')
        data=response.json()
        if data.get('session_id')!=session['native_session_id']:raise ServiceError(409,'原生会话绑定不一致')
        def scrub(value):
            if isinstance(value,str):return clean(value,secrets)
            if isinstance(value,list):return [scrub(v) for v in value]
            if isinstance(value,dict):return {k:scrub(v) for k,v in value.items()}
            return value
        data=scrub(data)
    except (httpx.HTTPError,ValueError):raise ServiceError(503,'原生记录暂不可用，请稍后重试') from None
    return data|{'conversation_id':ident,'provider':'claude_code','connection_name':snap.get('name','现有服务器连接'),'interaction':'managed_chat','capabilities':{'structured_history':True,'streaming':True,'terminal':False,'permission_reply':False}}
