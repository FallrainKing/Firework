#!/usr/bin/env python3
"""Portable Firework REST client. Python standard library only."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys
from urllib import request, error, parse

class ClientError(ValueError):
    pass

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ClientError('Redirect refused; use the canonical Firework HTTPS address')

def configuration():
    base=os.environ.get('FIREWORK_URL','').rstrip('/')
    u=parse.urlsplit(base)
    local=u.hostname in ('localhost','127.0.0.1','::1')
    if not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/') or any(c.isspace() for c in base) or '\\' in base or not (u.scheme=='https' or u.scheme=='http' and local and os.environ.get('FIREWORK_ALLOW_LOCAL_HTTP')=='1'):
        raise ClientError('Set FIREWORK_URL to a canonical HTTPS origin without credentials, path or query')
    filename=os.environ.get('FIREWORK_TOKEN_FILE')
    if filename:
        p=Path(filename)
        if p.is_symlink() or not p.is_file() or os.name!='nt' and stat.S_IMODE(p.stat().st_mode)&0o077:
            raise ClientError('Token file must be a regular private file (chmod 600)')
        secret=p.read_text().strip()
    else:secret=os.environ.get('FIREWORK_TOKEN','')
    if not secret.startswith('fw_') or not 20<len(secret)<=100 or any(c.isspace() for c in secret):
        raise ClientError('Set FIREWORK_TOKEN_FILE or FIREWORK_TOKEN to a valid external authorization')
    return base,secret

def call(method,path,body=None,key=None):
    base,secret=configuration()
    headers={'Authorization':'Bearer '+secret,'Accept':'application/json'}
    raw=None
    if body is not None:
        if not key or len(key)>80 or any(ord(c)<33 or ord(c)>126 for c in key):raise ClientError('Writes require a stable printable Idempotency-Key (1–80 characters)')
        raw=json.dumps(body,ensure_ascii=False).encode()
        if len(raw)>65536:raise ClientError('Request exceeds 64 KiB')
        headers.update({'Content-Type':'application/json','Idempotency-Key':key})
    req=request.Request(base+'/api/external/v1'+path,data=raw,headers=headers,method=method)
    try:
        with request.build_opener(NoRedirect()).open(req,timeout=30) as res:
            raw=res.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:raise ClientError('Response too large; narrow the request')
            return json.loads(raw)
    except error.HTTPError as exc:
        # Server/proxy error bodies are untrusted and may echo request headers.
        raise ClientError(f'Firework HTTP {exc.code}; 401: renew authorization, 403/404: check scope, 409: refresh version, 429: wait. No automatic write retry.') from None
    except error.URLError:raise ClientError('Unable to reach Firework; check address and connection') from None

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['capabilities','search','collections','show','document','page','annotations','create-paper','edit-paper','add-note','edit-note'])
    p.add_argument('--paper',type=int);p.add_argument('--page',type=int);p.add_argument('--annotation')
    p.add_argument('--query',default='');p.add_argument('--limit',type=int,default=20);p.add_argument('--offset',type=int,default=0)
    p.add_argument('--json-file',type=Path);p.add_argument('--request-key')
    a=p.parse_args(argv);cmd=a.command
    if cmd in ('capabilities','collections'):path='/'+cmd
    elif cmd=='search':path='/papers?'+parse.urlencode({'q':a.query,'limit':a.limit,'offset':a.offset})
    elif cmd=='create-paper':path='/papers'
    else:
        if not a.paper or a.paper<1:p.error('--paper must be a positive ID')
        path='/papers/'+str(a.paper)
        if cmd in ('annotations','add-note','edit-note'):path+='/annotations'
        if cmd=='edit-note':
            if not a.annotation or not all(c.isalnum() or c in '-_' for c in a.annotation):p.error('--annotation requires an ID')
            path+='/'+a.annotation
        if cmd=='document':path+='/document'
        if cmd=='page':
            if not a.page or a.page<1:p.error('--page must be positive')
            path+='/pages/'+str(a.page)
    writes={'create-paper':'POST','edit-paper':'PATCH','add-note':'POST','edit-note':'PATCH'}
    try:
        body=None
        if cmd in writes:
            if not a.json_file or not a.request_key:p.error('Writes require --json-file and --request-key')
            if a.json_file.stat().st_size>65536:raise ClientError('Input exceeds 64 KiB')
            body=json.loads(a.json_file.read_text())
            if not isinstance(body,dict):raise ClientError('JSON input must be an object')
        print(json.dumps(call(writes.get(cmd,'GET'),path,body,a.request_key),ensure_ascii=False,indent=2))
        return 0
    except ClientError as exc:
        print(str(exc),file=sys.stderr)
        return 1
    except (ValueError,OSError):
        # Never print arbitrary exceptions that might contain secret values.
        print('Firework operation failed. Check URL, private token file, JSON fields, authorization scope and current versions. No automatic retry.',file=sys.stderr)
        return 1
if __name__=='__main__':sys.exit(main())
