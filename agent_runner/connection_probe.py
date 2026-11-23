"""Bounded probes from the same Runner network boundary; no tools or user material."""
import asyncio,json,time
import httpx
from .connections import validate_destination

async def probe(snapshot,secret,kind,client_factory=httpx.AsyncClient):
    started=time.monotonic()
    try:await asyncio.to_thread(validate_destination,snapshot['base_url'])
    except ValueError:return {'status':'failed','reason':'destination_rejected','model_called':False}
    headers={'anthropic-version':'2023-06-01','content-type':'application/json'}
    if kind=='model':headers['x-api-key' if snapshot['auth_type']=='api_key' else 'authorization']=secret if snapshot['auth_type']=='api_key' else 'Bearer '+secret
    try:
        async with client_factory(timeout=httpx.Timeout(10,read=25),follow_redirects=False,trust_env=False) as client:
            method='POST' if kind=='model' else 'GET'
            args={'json':{'model':snapshot['model'].removesuffix('[1M]').removesuffix('[1m]'),'max_tokens':32,'stream':True,'messages':[{'role':'user','content':'Reply with OK.'}]}} if kind=='model' else {}
            url=snapshot['base_url'].rstrip('/')+('/v1/messages' if kind=='model' else '')
            async with client.stream(method,url,headers=headers,**args) as response:
                code=response.status_code
                result={'http_status':code,'latency_ms':round((time.monotonic()-started)*1000),'model_called':kind=='model','request_id':None}
                # Do not echo provider strings/headers that may contain credentials.
                if kind=='network':return result|{'status':'reachable' if code<500 else 'service_error','authentication_verified':False}
                if code!=200:return result|{'status':'failed','reason':{401:'authentication',403:'authorization',404:'model_or_endpoint',429:'rate_limited'}.get(code,'upstream_error')}
                total=0;buffer='';text=False;finished=False
                async for chunk in response.aiter_text():
                    total+=len(chunk)
                    if total>65536:return result|{'status':'failed','reason':'response_too_large'}
                    buffer+=chunk
                    while '\n' in buffer:
                        line,buffer=buffer.split('\n',1)
                        if not line.startswith('data:'):continue
                        try:item=json.loads(line[5:].strip())
                        except ValueError:continue
                        if item.get('type')=='error':return result|{'status':'failed','reason':'stream_error'}
                        if item.get('type')=='content_block_delta' and item.get('delta',{}).get('text'):text=True
                        if item.get('type')=='message_stop':finished=True
                return result|{'status':'passed' if text and finished else 'failed','reason':None if text and finished else 'incompatible_or_incomplete_stream','stream_verified':text and finished}
    except httpx.TimeoutException:return {'status':'failed','reason':'timeout','model_called':kind=='model'}
    except httpx.HTTPError:return {'status':'failed','reason':'network_or_tls','model_called':kind=='model'}
