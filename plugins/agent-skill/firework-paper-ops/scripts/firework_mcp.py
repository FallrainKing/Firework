#!/usr/bin/env python3
"""Firework stdio MCP: explicit domain tools, no arbitrary URLs, SQL or browser access."""
import base64,hashlib,json,os,sys
from pathlib import Path
from urllib import request,parse,error
from firework import call,configuration,ClientError,NoRedirect

V='2025-11-25'
def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
integer={'type':'integer','minimum':1};string={'type':'string'}
TOOLS={
 'firework_list_contexts':('List explicitly shared live windows; never guess the active target.',obj({})),
 'firework_get_context':('Read one authorized window and check its revision.',obj({'context_id':string,'expected_revision':integer},['context_id'])),
 'firework_read_current_resource':('Read the explicitly selected current resource, rejecting changed contexts.',obj({'context_id':string,'expected_revision':integer},['context_id','expected_revision'])),
 'firework_read_shared_selection':('Read an explicitly shared, expiring source selection.',obj({'selection_id':string},['selection_id'])),
 'firework_search_papers':('Search permitted library records.',obj({'query':string})),
 'firework_get_paper':('Read an existing paper record.',obj({'paper_id':integer},['paper_id'])),
 'firework_get_document':('Get the current PDF identity before reading or annotating.',obj({'paper_id':integer},['paper_id'])),
 'firework_read_page':('Read actual source-page text.',obj({'paper_id':integer,'page':integer},['paper_id','page'])),
 'firework_annotations':('Read paper annotations.',obj({'paper_id':integer},['paper_id'])),
 'firework_list_artifacts':('List permitted research outputs.',obj({'query':string})),
 'firework_get_artifact':('Read a saved artifact revision.',obj({'id':string,'revision':integer},['id'])),
 'firework_create_artifact':('Save a result; does not execute models or publish knowledge.',obj({'body':{'type':'object'},'request_key':string},['body','request_key'])),
 'firework_update_artifact':('Save a new artifact revision using expected_revision.',obj({'id':string,'body':{'type':'object'},'request_key':string},['id','body','request_key'])),
 'firework_submit_research':('Submit research-submission/v1: artifact, verified annotations and optional translation. Includes client_job_id. No fake server Run.',obj({'body':{'type':'object'},'request_key':string},['body','request_key'])),
 'firework_sync_receipt':('Reconcile an unknown write outcome using the original client_job_id.',obj({'client_job_id':string},['client_job_id'])),
 'firework_submit_knowledge':('Propose knowledge for Web review; cannot publish it.',obj({'body':{'type':'object'},'request_key':string},['body','request_key'])),
 'firework_recall_knowledge':('Search published knowledge with current authorized sources.',obj({'query':string})),
 'firework_frontier_topics':('List permitted frontier topics.',obj({})),
 'firework_frontier_reports':('Read frontier report timeline.',obj({'topic_id':integer})),
 'firework_submit_frontier_report':('Upload local frontier findings to an existing topic; candidates remain pending.',obj({'topic_id':integer,'body':{'type':'object'},'request_key':string},['topic_id','body','request_key'])),
 'firework_create_frontier_topic':('Create a paused frontier topic using the existing domain contract.',obj({'body':{'type':'object'},'request_key':string},['body','request_key'])),
 'firework_add_annotation':('Create a source-verified annotation.',obj({'paper_id':integer,'body':{'type':'object'},'request_key':string},['paper_id','body','request_key'])),
 'firework_get_annotation':('Read the current annotation and ETag, including recoverable deletion.',obj({'paper_id':integer,'annotation_id':string},['paper_id','annotation_id'])),
 'firework_update_annotation':('Update or soft-delete an annotation using its current expected_etag.',obj({'paper_id':integer,'annotation_id':string,'body':{'type':'object'},'request_key':string},['paper_id','annotation_id','body','request_key'])),
 'firework_upload_file':('Upload a permitted research file under FIREWORK_UPLOAD_ROOT; content-addressed deduplication.',obj({'paper_id':integer,'file_path':string},['paper_id','file_path'])),
 'firework_download_pdf':('Download a permitted paper PDF into FIREWORK_UPLOAD_ROOT for local work.',obj({'paper_id':integer},['paper_id'])),
}

def ident(value):
    if not isinstance(value,str) or len(value)>80 or not value or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-' for c in value):raise ClientError('Invalid resource ID')
    return parse.quote(value,safe='')

def transfer(args,upload):
    root_value=os.getenv('FIREWORK_UPLOAD_ROOT')
    if not root_value:raise ClientError('Configure FIREWORK_UPLOAD_ROOT as the explicitly permitted local research directory')
    root=Path(root_value).resolve()
    if not root.is_dir():raise ClientError('Research directory unavailable')
    base,secret=configuration();headers={'Authorization':'Bearer '+secret}
    if upload:
        p=Path(args['file_path']).resolve();p.relative_to(root)
        token=os.getenv('FIREWORK_TOKEN_FILE')
        if token and p==Path(token).resolve():raise ClientError('Credential files cannot be uploaded')
        if not p.is_file() or p.stat().st_size>30*1024*1024 or p.suffix.lower() not in ('.pdf','.png','.jpg','.jpeg','.txt','.md','.json'):raise ClientError('Unsupported research file')
        content=p.read_bytes();boundary='fw'+os.urandom(16).hex()
        filename=p.name.replace('"','_').replace('\r','_').replace('\n','_').encode()
        raw=(f'--{boundary}\r\nContent-Disposition: form-data; name="paper_id"\r\n\r\n{args["paper_id"]}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="'.encode()+filename+b'"\r\nContent-Type: application/octet-stream\r\n\r\n'+content+f'\r\n--{boundary}--\r\n'.encode())
        headers['Content-Type']='multipart/form-data; boundary='+boundary
        req=request.Request(base+'/api/external/v1/files',data=raw,headers=headers,method='POST')
    else:req=request.Request(base+f'/api/external/v1/papers/{args["paper_id"]}/file',headers=headers)
    try:
        with request.build_opener(NoRedirect()).open(req,timeout=60) as response:
            raw=response.read(50*1024*1024+1)
            if len(raw)>50*1024*1024:raise ClientError('File exceeds transfer limit')
            if upload:return json.loads(raw)
            if not raw.startswith(b'%PDF-'):raise ClientError('Not a PDF')
            digest=hashlib.sha256(raw).hexdigest();dest=root/f'paper-{args["paper_id"]}-{digest[:12]}.pdf'
            if dest.is_symlink():raise ClientError('Destination cannot be a link')
            if not dest.exists():
                with dest.open('xb') as stream:stream.write(raw)
            elif hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:raise ClientError('Existing file checksum mismatch')
            return {'file_path':str(dest),'sha256':digest,'paper_id':args['paper_id']}
    except (error.URLError,error.HTTPError):raise ClientError('Transfer failed; check connection, scopes and original outcome before retrying') from None

def invoke(name,a):
    if name not in TOOLS:raise ClientError('Unknown tool')
    schema=TOOLS[name][1]
    if not isinstance(a,dict) or set(a)-set(schema['properties']) or any(k not in a for k in schema['required']):raise ClientError('Invalid tool arguments')
    for k,v in a.items():
        t=schema['properties'][k].get('type')
        if t=='integer' and (not isinstance(v,int) or isinstance(v,bool) or v<1):raise ClientError('Invalid numeric identifier')
        if t=='string' and (not isinstance(v,str) or len(v)>4000):raise ClientError('Invalid string argument')
        if t=='object' and not isinstance(v,dict):raise ClientError('Expected a structured JSON object')
    if name=='firework_upload_file':return transfer(a,True)
    if name=='firework_download_pdf':return transfer(a,False)
    method='GET';body=None;key=a.get('request_key');q=lambda d:'?'+parse.urlencode(d)
    paths={
      'firework_list_contexts':'/contexts','firework_search_papers':'/papers'+q({'q':a.get('query','')}),'firework_list_artifacts':'/artifacts'+q({'q':a.get('query','')}),
      'firework_recall_knowledge':'/knowledge/recall'+q({'q':a.get('query','')}),'firework_frontier_topics':'/frontier/topics','firework_frontier_reports':'/frontier/reports'+(q({'topic_id':a['topic_id']}) if a.get('topic_id') else ''),
    }
    if name in paths:path=paths[name]
    elif name in ('firework_get_context','firework_read_current_resource'):
        path='/contexts/'+ident(a['context_id'])+('/resource' if name.endswith('resource') else '')
        if a.get('expected_revision'):path+=q({'expected_revision':a['expected_revision']})
    elif name=='firework_read_shared_selection':path='/selections/'+ident(a['selection_id'])
    elif name in ('firework_get_paper','firework_get_document','firework_read_page','firework_annotations'):
        path='/papers/'+str(a['paper_id'])+{'firework_get_paper':'','firework_get_document':'/document','firework_read_page':'/pages/'+str(a.get('page','')),'firework_annotations':'/annotations'}[name]
    elif name=='firework_get_artifact':path='/artifacts/'+ident(a['id'])+(q({'revision':a['revision']}) if a.get('revision') else '')
    elif name=='firework_get_annotation':path='/papers/'+str(a['paper_id'])+'/annotations/'+ident(a['annotation_id'])
    elif name=='firework_sync_receipt':path='/research-submissions/'+ident(a['client_job_id'])
    else:
        method='PATCH' if name in ('firework_update_artifact','firework_update_annotation') else 'POST';body=a['body']
        path={'firework_update_annotation':'/papers/'+str(a.get('paper_id',0))+'/annotations/'+ident(a.get('annotation_id','missing')),'firework_create_artifact':'/artifacts','firework_update_artifact':'/artifacts/'+ident(a.get('id','missing')),'firework_submit_research':'/research-submissions','firework_submit_knowledge':'/knowledge/candidates','firework_create_frontier_topic':'/frontier/topics','firework_submit_frontier_report':'/frontier/topics/'+str(a.get('topic_id',0))+'/reports','firework_add_annotation':'/papers/'+str(a.get('paper_id',0))+'/annotations'}.get(name)
        if not path:raise ClientError('Unsupported operation')
    return call(method,path,body,key)

def handle(message):
    mid=message.get('id');method=message.get('method');p=message.get('params') or {}
    if mid is None:return None
    try:
        if method=='initialize':result={'protocolVersion':p.get('protocolVersion') if p.get('protocolVersion') in ('2025-11-25','2025-06-18','2024-11-05') else V,'capabilities':{'tools':{'listChanged':False},'resources':{}},'serverInfo':{'name':'firework','version':'0.1.0'}}
        elif method=='ping':result={}
        elif method=='tools/list':result={'tools':[{'name':n,'description':d,'inputSchema':s} for n,(d,s) in TOOLS.items()]}
        elif method=='tools/call':
            try:
                data=invoke(p.get('name'),p.get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}],'structuredContent':data if isinstance(data,dict) else {'result':data},'isError':False}
            except ClientError as exc:result={'content':[{'type':'text','text':str(exc)}],'isError':True}
            except (ValueError,OSError):result={'content':[{'type':'text','text':'Operation failed. Check arguments and original request key. No automatic retry.'}],'isError':True}
        elif method=='resources/list':result={'resources':[{'uri':'firework://contexts','name':'Shared Firework windows','mimeType':'application/json'}]}
        elif method=='resources/templates/list':result={'resourceTemplates':[{'uriTemplate':'firework://contexts/{id}','name':'Shared window context','mimeType':'application/json'}]}
        elif method=='resources/read':
            uri=p.get('uri','');parsed=parse.urlsplit(uri)
            if uri=='firework://contexts':data=invoke('firework_list_contexts',{})
            elif parsed.scheme=='firework' and parsed.netloc=='contexts' and not parsed.query and not parsed.fragment:data=invoke('firework_get_context',{'context_id':parsed.path.lstrip('/')})
            else:raise ClientError('Unknown resource')
            result={'contents':[{'uri':uri,'mimeType':'application/json','text':json.dumps(data,ensure_ascii=False)}]}
        else:return {'jsonrpc':'2.0','id':mid,'error':{'code':-32601,'message':'Method not found'}}
        return {'jsonrpc':'2.0','id':mid,'result':result}
    except Exception:return {'jsonrpc':'2.0','id':mid,'error':{'code':-32602,'message':'Invalid request or inaccessible resource'}}

def main():
    for line in sys.stdin:
        if len(line)>2*1024*1024:response={'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Request too large'}}
        else:
            try:
                message=json.loads(line)
                if not isinstance(message,dict):raise ValueError()
                response=handle(message)
            except ValueError:response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        if response is not None:print(json.dumps(response,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
