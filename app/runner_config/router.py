from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict
from . import budgets
from app.skills.service import execution_policy,ensure_builtin_skills
from app.core.errors import ServiceError
router=APIRouter(prefix='/runner/budgets',tags=['runner configuration'])

@router.get('')
def list_budgets(request:Request):return budgets.listing(request.app.state.db)
@router.post('',status_code=201)
def create_budget(body:budgets.BudgetWrite,request:Request):return budgets.save(request.app.state.db,body)
@router.patch('/{ident}')
def update_budget(ident:str,body:budgets.BudgetWrite,request:Request):return budgets.save(request.app.state.db,body,ident)
@router.put('/default')
def default_budget(body:budgets.DefaultWrite,request:Request):return budgets.set_default(request.app.state.db,body)
class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    skill:str='chat'
    budget:budgets.BudgetRef|None=None
    inherit_skill:bool=False
@router.post('/preflight')
def preview(body:Preview,request:Request):
    ensure_builtin_skills(request.app.state.db)
    try:policy=execution_policy(request.app.state.db,body.skill)
    except ValueError as e:raise ServiceError(422,str(e)) from None
    p=policy if body.inherit_skill else budgets.resolve(request.app.state.db,policy,body.budget)
    return {'skill':body.skill,'budget_snapshot':p.get('budget_snapshot'),'effective':{k:p.get(k) for k in budgets.KEYS},'tools':p['tools'],'cost_verified':False,'warning':'仅校验配置，不调用模型。金额为 CLI 估价守卫，非账单硬限额；累计 token/请求级限制尚未实现。'}
