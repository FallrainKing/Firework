"""Build an isolated environment; never alter ~/.claude or inherit host auth."""
import ipaddress
import json
import os
import socket
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

SAFE_ENV=('PATH','HOME','USER','LANG','LC_ALL','HTTPS_PROXY','HTTP_PROXY','NO_PROXY')

def validate_destination(base_url):
    u=urlsplit(base_url)
    allowed={h.strip().lower() for h in os.getenv('FIREWORK_RUNNER_ALLOW_PRIVATE_HOSTS','').split(',') if h.strip()}
    host=u.hostname.lower()
    if host in allowed:return
    if u.scheme!='https':raise ValueError('自定义 API 默认要求 HTTPS；内网地址需管理员明确授权')
    try:addresses={r[4][0] for r in socket.getaddrinfo(host,u.port or 443,type=socket.SOCK_STREAM)}
    except OSError:raise ValueError('API 地址解析失败；未调用模型') from None
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError('API 地址指向私有或保留网络，需管理员明确授权')

def check_current(runtime,snap):
    path=Path(runtime).parent/'app.db'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM runner_connections WHERE id=?',(snap['id'],)).fetchone()
        if not row or not row['enabled'] or row['revision']!=snap['revision']:
            raise ValueError('连接已停用或修订；未调用模型，请重新创建会话')
        expected=json.loads(row['config_json'])|{'id':row['id'],'revision':row['revision'],'name':row['name']}
        if expected!=snap:raise ValueError('连接快照不匹配；未调用模型')

def environment(runtime,snap,secret):
    if not secret:raise ValueError('当前账号的连接没有凭据；不会回退宿主机凭据')
    validate_destination(snap['base_url'])
    env={k:v for k,v in os.environ.items() if k in SAFE_ENV}
    config=Path(runtime)/'connections'/f"{snap['id']}-{snap['revision']}"/'claude-config'
    config.mkdir(parents=True,exist_ok=True,mode=0o700)
    env.update(CLAUDE_CONFIG_DIR=str(config),CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',MAX_THINKING_TOKENS='0',
               ANTHROPIC_BASE_URL=snap['base_url'],ANTHROPIC_MODEL=snap['model'])
    for tier in ('SONNET','OPUS','HAIKU','FABLE'):env['ANTHROPIC_DEFAULT_'+tier+'_MODEL']=snap['model']
    env['CLAUDE_CODE_SUBAGENT_MODEL']=snap['model']
    env['ANTHROPIC_API_KEY' if snap['auth_type']=='api_key' else 'ANTHROPIC_AUTH_TOKEN']=secret
    return env

def redact(value,secret):
    if not secret:return value
    if isinstance(value,str):return value.replace(secret,'[REDACTED]')
    if isinstance(value,list):return [redact(x,secret) for x in value]
    if isinstance(value,dict):return {k:redact(v,secret) for k,v in value.items()}
    return value


def mcp_command(script):
    import sys
    launcher="import os,sys; clean={k:v for k,v in os.environ.items() if not k.startswith('ANTHROPIC_') and k!='CLAUDE_CODE_OAUTH_TOKEN'}; os.execve(sys.executable,[sys.executable,sys.argv[1]],clean)"
    return {'command':sys.executable,'args':['-c',launcher,str(script)]}
