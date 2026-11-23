"""A per-terminal model relay. No general proxy, redirects or host credentials in PTY."""
import asyncio
import contextlib
import hmac
import json
from pathlib import Path
import httpx
import uvicorn
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,StreamingResponse
from .connections import validate_destination

class ModelBridge:
    def __init__(self,folder,base_url,secret,auth_type,model,token):
        self.path=Path(folder)/'model.sock';self.base=base_url.rstrip('/');self.secret=secret
        self.auth_type=auth_type;self.model=model;self.token=token;self.calls=0;self.message_calls=0;self.armed=False;self.authorize=lambda:True
        self.client=httpx.AsyncClient(timeout=httpx.Timeout(15,read=None),follow_redirects=False,trust_env=False)
        self.app=FastAPI(docs_url=None,openapi_url=None,redoc_url=None)
        self.app.add_api_route('/{path:path}',self.forward,methods=['GET','POST','PUT','PATCH','DELETE'])
    async def forward(self,request:Request,path:str):
        key=request.headers.get('x-api-key') or request.headers.get('authorization','').removeprefix('Bearer ')
        if not hmac.compare_digest(key.encode(),self.token.encode()):return JSONResponse({'error':{'message':'Terminal authorization expired'}},401)
        if (request.method,path) not in {('POST','v1/messages'),('POST','v1/messages/count_tokens'),('GET','v1/models')} or (request.url.query and not (path=='v1/messages' and str(request.url.query)=='beta=true')):
            return JSONResponse({'error':{'message':'Only the configured model API is available'}},403)
        if not self.authorize():return JSONResponse({'error':{'message':'Account or model authorization revoked'}},403)
        if path=='v1/messages' and not self.armed:return JSONResponse({'error':{'message':'Submit input in the terminal before model execution'}},403)
        body=bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body)>16*1024*1024:return JSONResponse({'error':{'message':'Model request too large'}},413)
        if request.method=='POST':
            try:data=json.loads(body)
            except ValueError:return JSONResponse({'error':{'message':'Invalid model request'}},400)
            if not isinstance(data,dict) or data.get('model') not in {self.model,self.model.removesuffix('[1M]').removesuffix('[1m]')}:return JSONResponse({'error':{'message':'Use the model selected for this terminal'}},409)
        headers={k:v for k,v in request.headers.items() if k.lower() in ('content-type','anthropic-version','anthropic-beta','accept')}
        headers['authorization' if self.auth_type=='bearer' else 'x-api-key']=('Bearer ' if self.auth_type=='bearer' else '')+self.secret
        try:
            await asyncio.to_thread(validate_destination,self.base)
            response=await self.client.send(self.client.build_request(request.method,self.base+'/'+path+('?beta=true' if request.url.query else ''),headers=headers,content=bytes(body)),stream=True)
        except (ValueError,httpx.HTTPError):return JSONResponse({'error':{'message':'Configured model connection unavailable'}},502)
        if 300<=response.status_code<400:
            await response.aclose();return JSONResponse({'error':{'message':'Model redirects are not allowed'}},502)
        self.calls+=1
        if path=='v1/messages':self.message_calls+=1
        async def chunks():
            try:
                pending=b'';key=self.secret.encode()
                async for part in response.aiter_bytes():
                    pending+=part
                    if len(pending)>len(key):
                        cut=len(pending)-max(0,len(key)-1)
                        # Keep any partial credential at the cut boundary.
                        for n in range(min(len(key)-1,cut),0,-1):
                            if pending[:cut].endswith(key[:n]):cut-=n;break
                        yield pending[:cut].replace(key,b'[REDACTED]') if key else pending[:cut]
                        pending=pending[cut:]
                if pending:yield pending.replace(key,b'[REDACTED]') if key else pending
            finally:await response.aclose()
        return StreamingResponse(chunks(),status_code=response.status_code,headers={'content-type':response.headers.get('content-type','application/json'),'cache-control':'no-store'})
    async def start(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.server=uvicorn.Server(uvicorn.Config(self.app,uds=str(self.path),log_level='critical',access_log=False,limit_concurrency=4))
        self.server.install_signal_handlers=lambda:None
        self.server.capture_signals=lambda:contextlib.nullcontext()
        self.task=asyncio.create_task(self.server.serve())
        for _ in range(100):
            if self.server.started:
                self.path.chmod(0o600);return
            if self.task.done():break
            await asyncio.sleep(.02)
        await self.close();raise ValueError('Model relay could not start')
    async def close(self):
        self.authorize=lambda:False
        self.secret='';self.token=''
        if hasattr(self,'server'):self.server.should_exit=True
        if hasattr(self,'task'):
            try:await asyncio.wait_for(self.task,3)
            except asyncio.TimeoutError:
                self.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await self.task
        await self.client.aclose()
        self.path.unlink(missing_ok=True)
