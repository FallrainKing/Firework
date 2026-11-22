from fastapi import APIRouter,Request
from . import profiles, connections
router=APIRouter(prefix='/api/me/runner',tags=['execution profiles'])
@router.get('/profiles')
def listing(request:Request):return profiles.listing(request.app.state.db)
@router.post('/profiles',status_code=201)
def create(body:profiles.ProfileWrite,request:Request):return profiles.save(request.app.state.db,request.app.state.settings,body)
@router.patch('/profiles/{ident}')
def update(ident:str,body:profiles.ProfileWrite,request:Request):
    if body.expected_revision is None:
        from ..core.errors import ServiceError
        raise ServiceError(422,'编辑需要 expected_revision')
    return profiles.save(request.app.state.db,request.app.state.settings,body,ident)
@router.post('/profiles/preflight')
def preview(body:profiles.ProfileConfig,request:Request):return profiles.effective(request.app.state.db,request.app.state.settings,body)
@router.get('/mcp')
def mcp():return profiles.tool_catalog()
@router.get('/models')
def models(request:Request):
    data=connections.listing(request.app.state.db,request.app.state.settings)
    return {'models':[{'connection_id':c['id'],'revision':c['revision'],'connection_name':c['name'],'enabled':c['enabled'],**{k:c['config'][k] for k in ('model','vision','context_window')},'verification':'not_tested'} for c in data['connections']], 'discovery':'configured_connections','model_called':False}
