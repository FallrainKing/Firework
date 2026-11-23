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
        # Print only allowlisted machine codes, never server/proxy detail text.
        messages={
            'context_changed':'The page has changed; read its new revision or explicitly work on the pinned resource.',
            'context_stale':'The window is offline or stale; do not treat it as the current page.',
            'idempotency_conflict':'This key belongs to a different method/path/body. Do not bypass it with a new key. Reconcile the original operation.',
            'metadata_conflict':'Read the current paper version, merge intended changes, then submit a new operation with a new key.',
            'annotation_conflict':'Read the annotation (including deleted records), merge changes against its current ETag, then use a new key.',
            'evidence_conflict':'Read the current document and page; verify the PDF hash, quote and geometry before a new operation.',
            'topic_conflict':'Read the current topic revision and reconcile the report before a new operation.',
        }
        code=None
        try:code=json.loads(exc.read(8192)).get('code')
        except (ValueError,AttributeError):pass
        advice=messages.get(code) if isinstance(code,str) else None
        if not advice:
            advice={401:'Renew authorization.',403:'Check scope.',404:'Check scope and existence.',429:'Wait before retrying.'}.get(exc.code,'Inspect the operation before retrying; do not overwrite or bypass a conflict.')
        raise ClientError(f'Firework HTTP {exc.code}: {advice} For an unknown write outcome, retry only the identical request with its original key. No automatic retry.') from None
    except error.URLError:raise ClientError('Unable to reach Firework; check address and connection') from None

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['capabilities','search','collections','show','document','page','annotations','create-paper','edit-paper','add-note','edit-note','note','frontier-topics','create-frontier-topic','frontier-reports','frontier-report','submit-frontier-report','artifacts','artifact','create-artifact','edit-artifact','submit-knowledge','recall-knowledge','run-timeline'])
    p.add_argument('--id');p.add_argument('--revision',type=int);p.add_argument('--after',type=int,default=0)
    p.add_argument('--paper',type=int);p.add_argument('--page',type=int);p.add_argument('--annotation')
    p.add_argument('--include-deleted',action='store_true');p.add_argument('--topic',type=int);p.add_argument('--report');p.add_argument('--before',type=int)
    p.add_argument('--query',default='');p.add_argument('--limit',type=int,default=20);p.add_argument('--offset',type=int,default=0)
    p.add_argument('--markdown-file',type=Path);p.add_argument('--json-file',type=Path);p.add_argument('--request-key')
    a=p.parse_args(argv);cmd=a.command
    if a.markdown_file and cmd!='submit-frontier-report':p.error('--markdown-file requires submit-frontier-report')
    if cmd in ('artifacts','create-artifact'):path='/artifacts'+('?' + parse.urlencode({'q':a.query,'limit':a.limit}) if cmd=='artifacts' else '')
    elif cmd in ('artifact','edit-artifact','run-timeline'):
        if not a.id or len(a.id)!=32 or any(c not in '0123456789abcdef' for c in a.id):p.error('--id requires a 32-character resource ID')
        path=('/runs/'+a.id+'/timeline?'+parse.urlencode({'after':a.after,'limit':a.limit})) if cmd=='run-timeline' else '/artifacts/'+a.id
        if cmd=='artifact' and a.revision:path+='?revision='+str(a.revision)
    elif cmd=='submit-knowledge':path='/knowledge/candidates'
    elif cmd=='recall-knowledge':path='/knowledge/recall?'+parse.urlencode({'q':a.query,'limit':a.limit})
    elif cmd in ('frontier-topics','create-frontier-topic'):path='/frontier/topics'
    elif cmd=='frontier-reports':
        params={'limit':a.limit}
        if a.topic:params['topic_id']=a.topic
        if a.before:params['before']=a.before
        path='/frontier/reports?'+parse.urlencode(params)
    elif cmd=='frontier-report':
        if not a.report or not all(c in '0123456789abcdef' for c in a.report) or len(a.report)!=32:p.error('--report requires a report run ID')
        path='/frontier/reports/'+a.report
    elif cmd=='submit-frontier-report':
        if not a.topic or a.topic<1:p.error('--topic must be positive')
        path='/frontier/topics/'+str(a.topic)+'/reports'
    elif cmd in ('capabilities','collections'):path='/'+cmd
    elif cmd=='search':path='/papers?'+parse.urlencode({'q':a.query,'limit':a.limit,'offset':a.offset})
    elif cmd=='create-paper':path='/papers'
    else:
        if not a.paper or a.paper<1:p.error('--paper must be a positive ID')
        path='/papers/'+str(a.paper)
        if cmd in ('annotations','add-note','edit-note','note'):path+='/annotations'
        if cmd in ('edit-note','note'):
            if not a.annotation or not all(c.isalnum() or c in '-_' for c in a.annotation):p.error('--annotation requires an ID')
            path+='/'+a.annotation
        if cmd=='annotations' and a.include_deleted:path+='?include_deleted=true'
        if cmd=='document':path+='/document'
        if cmd=='page':
            if not a.page or a.page<1:p.error('--page must be positive')
            path+='/pages/'+str(a.page)
    writes={'create-artifact':'POST','edit-artifact':'PATCH','submit-knowledge':'POST','create-paper':'POST','edit-paper':'PATCH','add-note':'POST','edit-note':'PATCH','create-frontier-topic':'POST','submit-frontier-report':'POST'}
    try:
        body=None
        if cmd in writes:
            if not a.json_file or not a.request_key:p.error('Writes require --json-file and --request-key')
            if a.json_file.stat().st_size>65536:raise ClientError('Input exceeds 64 KiB')
            body=json.loads(a.json_file.read_text(encoding='utf-8'))
            if not isinstance(body,dict):raise ClientError('JSON input must be an object')
            if a.markdown_file:
                if cmd!='submit-frontier-report':raise ClientError('--markdown-file is only supported for submit-frontier-report')
                if a.markdown_file.stat().st_size>65536:raise ClientError('Markdown exceeds request limit')
                body['markdown']=a.markdown_file.read_text(encoding='utf-8')
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
