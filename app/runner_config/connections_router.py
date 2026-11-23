from fastapi import APIRouter,Request
from . import connections
from .connection_schemas import ConnectionWrite,ConnectionDefault,ConnectionRef
from pydantic import BaseModel,ConfigDict,Field
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

@router.get('/presets')
def presets():
    from .presets import PRESETS
    return {'presets':PRESETS,'protocol':'anthropic_messages'}

from . import testing
@router.post('/{ident}/tests',status_code=202)
async def start_test(ident:str,body:testing.TestRequest,request:Request):return await testing.start(request.app.state,ident,body)
@router.get('/tests/{tid}')
def get_test(tid:str,request:Request):return testing.view(request.app.state,tid)
@router.post('/tests/{tid}/cancel')
async def cancel_test(tid:str,request:Request):return await testing.cancel(request.app.state,tid)

class AddModel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    model:str=Field(min_length=1,max_length=150,pattern=r'^[^\x00-\x1f]+$')
    expected_revision:int
@router.post('/{ident}/models',status_code=201)
def add_model(ident:str,body:AddModel,request:Request):
    from .connection_schemas import ConnectionWrite,ConnectionConfig
    from pydantic import SecretStr
    db=request.app.state.db;settings=request.app.state.settings
    row=db.execute('SELECT * FROM runner_connections WHERE id=?',(ident,)).fetchone()
    from ..core.errors import ServiceError
    if not row:raise ServiceError(404,'连接不存在')
    if row['revision']!=body.expected_revision:raise ServiceError(409,'连接已变化')
    import json
    if not body.model.strip():raise ServiceError(422,'模型名称不能为空')
    config=json.loads(row['config_json']);config['model']=body.model.strip()
    new=connections.save(db,settings,ConnectionWrite(name=(row['name']+' · '+body.model)[:80],config=ConnectionConfig(**config),api_key=SecretStr(connections.decrypt(settings,ident,row['secret_cipher']))))
    with db:db.execute('INSERT INTO connection_models VALUES (?,?)',(ident,new['id']))
    return new
