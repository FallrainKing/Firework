"""Versioned execution plans narrow existing Skills; never introduce shell/MCP privileges."""
import json
import uuid
from pydantic import BaseModel, ConfigDict, Field
from ..core.errors import ServiceError
from ..skills import service as skills
from . import budgets, connections
from .connection_schemas import ConnectionRef

class ProfileRef(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    revision:int=Field(ge=1)

class ProfileConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    skill_id:str=Field(min_length=1,max_length=100)
    skill_version_id:int=Field(ge=1)
    connection:ConnectionRef|None=None
    budget:budgets.BudgetRef
    role_prompt:str=Field('',max_length=6000)
    tools:list[str]=Field(default_factory=list,max_length=13)

class ProfileWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=80)
    config:ProfileConfig
    enabled:bool=True
    expected_revision:int|None=Field(None,ge=1)

def item(r):
    return {k:r[k] for k in ('id','name','revision','updated_at')}|{'enabled':bool(r['enabled']),'config':json.loads(r['config_json'])}

def listing(db):
    return {'profiles':[item(r) for r in db.execute('SELECT * FROM runner_profiles ORDER BY rowid DESC')]}

def effective(db,settings,cfg):
    skills.ensure_builtin_skills(db)
    if cfg.skill_id in ('paper_guide','frontier_monitor','paper_import'):
        raise ServiceError(422,'此 Skill 需要专用任务上下文，请从对应功能入口执行')
    try:p=skills.execution_policy(db,cfg.skill_id,cfg.skill_version_id)
    except ValueError as e:raise ServiceError(409,str(e)) from None
    if len(set(cfg.tools))!=len(cfg.tools) or not set(cfg.tools)<=set(p['tools']):
        raise ServiceError(422,'执行方案只能缩小所选 Skill 的工具权限')
    snap=connections.snapshot(db,settings,cfg.connection,None if cfg.connection else '{"mode":"legacy"}')
    p=budgets.resolve(db,p,cfg.budget)
    p['tools']=cfg.tools
    if snap.get('mode')=='custom' and p['max_output_tokens']>snap['context_window']:
        raise ServiceError(422,'输出额度超过模型声明的上下文容量')
    return {'connection':snap,'policy':p,'role_prompt':cfg.role_prompt,'model_called':False}

def save(db,settings,body,ident=None):
    name=body.name.strip()
    if not name:raise ServiceError(422,'方案名称不能为空')
    if body.enabled:effective(db,settings,body.config)
    ident=ident or uuid.uuid4().hex
    with db:
        if body.expected_revision is None:
            if db.execute('SELECT 1 FROM runner_profiles WHERE id=?',(ident,)).fetchone():raise ServiceError(409,'缺少预期修订')
            db.execute('INSERT INTO runner_profiles(id,name,config_json,enabled) VALUES (?,?,?,?)',(ident,name,body.config.model_dump_json(),int(body.enabled)))
        else:
            cur=db.execute('UPDATE runner_profiles SET name=?,config_json=?,enabled=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?',(name,body.config.model_dump_json(),int(body.enabled),ident,body.expected_revision))
            if cur.rowcount!=1:raise ServiceError(409,'方案不存在或已更新，请刷新')
    return item(db.execute('SELECT * FROM runner_profiles WHERE id=?',(ident,)).fetchone())

def resolve(db,settings,ref):
    row=db.execute('SELECT * FROM runner_profiles WHERE id=?',(ref.id,)).fetchone()
    if not row or not row['enabled'] or row['revision']!=ref.revision:raise ServiceError(409,'执行方案已停用或修订，请新建会话或重新选择')
    cfg=ProfileConfig.model_validate_json(row['config_json'])
    resolved=effective(db,settings,cfg)
    resolved['snapshot']={'id':row['id'],'revision':row['revision'],'name':row['name'],'config':cfg.model_dump()}
    return resolved

def tool_catalog():
    from ..skills.service import ALLOWED_TOOLS
    writes={'paper_import','frontier_report','reader_guide_submit'}
    return {'servers':[{'id':'research','transport':'private-stdio','managed':True,'tools':[{'name':t,'effect':'scoped_write' if t in writes else 'read','grant':'skill AND profile AND task binding'} for t in sorted(ALLOWED_TOOLS)]}], 'external_servers_enabled':False,'model_called':False}
