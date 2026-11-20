"""Fail-closed authentication and trusted workspace routing before every API."""
import hmac
from pathlib import Path
from types import SimpleNamespace
from starlette.requests import Request
from starlette.responses import JSONResponse
from ..core.workspaces import workspace_context,valid_workspace,workspace_path
from .store import COOKIE

SAFE={'GET','HEAD','OPTIONS'}
PUBLIC={'/api/auth/session','/api/auth/login','/api/auth/register','/api/zotero/pair/start','/api/zotero/pair/claim'}


def same_origin(request,store):
    origin=request.headers.get('origin')
    return (not origin or origin==store.public_origin) and request.headers.get('sec-fetch-site')!='cross-site'


class AuthenticationMiddleware:
    def __init__(self,app):self.app=app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        request=Request(scope,receive)
        original=scope['app']
        path=scope['path']
        protected=path.startswith('/api/') or path in ('/docs','/redoc','/openapi.json')
        store=getattr(original.state,'auth_store',None)
        user=None;key='legacy'
        if protected and store is None:
            return await JSONResponse({'detail':'认证服务尚未就绪'},status_code=503)(scope,receive,send)
        if protected:
            if path.startswith('/api/internal/'):
                key=request.headers.get('x-research-workspace','legacy')
                supplied=request.headers.get('x-research-tool-token','')
                if not valid_workspace(key) or not store.by_workspace(key) or not supplied:
                    return await JSONResponse({'detail':'工具未授权'},status_code=403)(scope,receive,send)
                token_file=workspace_path(store.root,key)/'agent/internal-token'
                expected=token_file.read_text().strip() if token_file.is_file() else ''
                if not expected or not hmac.compare_digest(supplied.encode(),expected.encode()):
                    return await JSONResponse({'detail':'工具未授权'},status_code=403)(scope,receive,send)
                account=store.by_workspace(key)
                if not store.login_allowed(account):
                    return await JSONResponse({'detail':'账号当前不可执行任务'},status_code=403)(scope,receive,send)
            elif path.startswith('/api/zotero/device/'):
                from ..integrations.zotero.auth import principal
                header=request.headers.get('authorization','')
                user=principal(store,header[7:]) if header.startswith('Bearer ') else None
                if user is None:
                    return await JSONResponse({'detail':'插件未配对、已过期或已撤销'},status_code=401)(scope,receive,send)
                key=user['workspace_key']
            elif path not in PUBLIC:
                user=store.session(request.cookies.get(store.cookie_name,''))
                if user is None:
                    return await JSONResponse({'detail':'请先登录'},status_code=401,headers={'Cache-Control':'no-store'})(scope,receive,send)
                if path.startswith('/api/admin/') and user['role']!='admin':
                    return await JSONResponse({'detail':'需要管理员权限'},status_code=403)(scope,receive,send)
                if path in ('/docs','/redoc','/openapi.json') and user['role']!='admin':
                    return await JSONResponse({'detail':'需要管理员权限'},status_code=403)(scope,receive,send)
                if request.method not in SAFE and (not same_origin(request,store) or not hmac.compare_digest(request.headers.get('x-csrf-token','').encode(),user['csrf'].encode())):
                    return await JSONResponse({'detail':'请求验证失败，请刷新后重试'},status_code=403)(scope,receive,send)
                key=user['workspace_key']
            elif request.method not in SAFE and (not same_origin(request,store) or 'application/json' not in request.headers.get('content-type','')):
                return await JSONResponse({'detail':'请求来源不允许'},status_code=403)(scope,receive,send)
            scope.setdefault('state',{})['auth_user']=user
            if path not in PUBLIC and not path.startswith('/api/admin/') and path not in ('/docs','/redoc','/openapi.json'):
                state=await original.state.workspaces.get(key)
                scope['app']=SimpleNamespace(state=state)
        context=workspace_context.set(key)
        async def guarded_send(message):
            if message['type']=='http.response.start':
                headers=[(k,v) for k,v in message.get('headers',[]) if k.lower() not in (b'cache-control',b'vary')]
                headers.extend([(b'cache-control',b'no-store'),(b'vary',b'Cookie'),(b'x-content-type-options',b'nosniff'),
                                (b'referrer-policy',b'same-origin'),(b'x-frame-options',b'DENY'),
                                (b'content-security-policy',b"frame-ancestors 'none'; object-src 'none'; base-uri 'self'")])
                message={**message,'headers':headers}
            await send(message)
        try:await self.app(scope,receive,guarded_send)
        finally:workspace_context.reset(context)
