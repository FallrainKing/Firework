from fastapi import APIRouter,Request
from . import connections
from .connection_schemas import ConnectionWrite,ConnectionDefault,ConnectionRef
from pydantic import BaseModel,ConfigDict
router=APIRouter(prefix='/runner/connections',tags=['runner connections'])
@router.get('')
def listing(request:Request):return connections.listing(request.app.state.db,request.app.state.settings)
@router.post('',status_code=201)
def create(body:ConnectionWrite,request:Request):return connections.save(request.app.state.db,request.app.state.settings,body)
@router.patch('/{ident}')
def update(ident:str,body:ConnectionWrite,request:Request):return connections.save(request.app.state.db,request.app.state.settings,body,ident)
@router.put('/default')
def default(body:ConnectionDefault,request:Request):return connections.set_default(request.app.state.db,request.app.state.settings,body)
class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    connection:ConnectionRef|None=None
    has_images:bool=False
@router.post('/preflight')
def preview(body:Preview,request:Request):
    from app.core.errors import ServiceError
    snap=connections.snapshot(request.app.state.db,request.app.state.settings,body.connection)
    if body.has_images and snap.get('mode')=='custom' and snap.get('vision')!='declared_yes':raise ServiceError(422,'该连接尚未声明支持图片，请选择支持视觉的模型')
    return {'snapshot':snap,'verification':'not_tested','model_called':False,'warning':'仅检查本地配置；保存不等于 API 可用、视觉或 1M 上下文已经验证。当前仅支持 Anthropic Messages 兼容接口。'}
