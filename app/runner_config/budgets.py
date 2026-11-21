"""Bounded budgets change amounts/counts, never Skill tool permissions."""
import json
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.errors import ServiceError

class BudgetValues(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    max_turns: int = Field(24, ge=1, le=100)
    max_output_tokens: int = Field(8192, ge=256, le=32768)
    max_calls: int = Field(24, ge=0, le=100)
    timeout_s: int = Field(1800, ge=30, le=7200)
    cost_mode: Literal['disabled','cli_estimate_guard'] = 'disabled'
    max_budget_usd: float | None = Field(None, gt=0, le=100)

    @model_validator(mode='after')
    def valid_cost(self):
        if self.cost_mode == 'cli_estimate_guard' and self.max_budget_usd is None:
            raise ValueError('CLI 估价守卫需要填写金额上限')
        if self.cost_mode == 'disabled' and self.max_budget_usd is not None:
            raise ValueError('关闭金额守卫时金额必须为空')
        return self

class BudgetRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)

class BudgetSnapshot(BudgetValues):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)

class BudgetWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    values: BudgetValues
    expected_revision: int | None = Field(None, ge=1)

class DefaultWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    budget_id: str | None = Field(None, max_length=80)
    expected_revision: int = Field(ge=1)

PRESETS = {
 'quick': ('快速问答', BudgetValues(max_turns=8,max_output_tokens=2048,max_calls=4,timeout_s=180)),
 'standard': ('标准研究', BudgetValues()),
 'deep': ('深度研究', BudgetValues(max_turns=40,max_output_tokens=16384,max_calls=48,timeout_s=3600)),
}
KEYS = ('max_turns','max_output_tokens','max_calls','timeout_s','max_budget_usd')

def ensure(db):
    with db:
        for key,(name,values) in PRESETS.items():
            raw=values.model_dump_json()
            db.execute('INSERT OR IGNORE INTO runner_budgets(id,name,builtin,values_json) VALUES (?,?,1,?)',(key,name,raw))
            db.execute('INSERT OR IGNORE INTO runner_budget_revisions(budget_id,revision,name,values_json) VALUES (?,1,?,?)',(key,name,raw))

def item(row):
    return {'id':row['id'],'name':row['name'],'revision':row['revision'],'builtin':bool(row['builtin']),'values':json.loads(row['values_json'])}

def listing(db):
    ensure(db)
    return {'budgets':[item(r) for r in db.execute('SELECT * FROM runner_budgets ORDER BY builtin DESC,rowid')], **dict(db.execute('SELECT default_budget_id,revision AS settings_revision FROM runner_budget_settings WHERE id=1').fetchone()), 'enforcement':{'max_turns':'cli','max_output_tokens':'cli','max_calls':'mcp_proxy','timeout_s':'runner','max_budget_usd':'cli_estimate_not_invoice'}}

def save(db,body,ident=None):
    ensure(db)
    name=body.name.strip()
    if not name: raise ServiceError(422,'名称不能为空')
    raw=body.values.model_dump_json()
    with db:
        if ident:
            row=db.execute('SELECT * FROM runner_budgets WHERE id=?',(ident,)).fetchone()
            if not row: raise ServiceError(404,'预算不存在')
            if row['builtin']: raise ServiceError(409,'内置预设请复制后修改')
            cur=db.execute('UPDATE runner_budgets SET name=?,values_json=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?',(name,raw,ident,body.expected_revision))
            if cur.rowcount!=1: raise ServiceError(409,'预算版本已变化，请重新载入')
            rev=row['revision']+1
        else:
            ident=uuid.uuid4().hex;rev=1
            db.execute('INSERT INTO runner_budgets(id,name,values_json) VALUES (?,?,?)',(ident,name,raw))
        db.execute('INSERT INTO runner_budget_revisions(budget_id,revision,name,values_json) VALUES (?,?,?,?)',(ident,rev,name,raw))
    return item(db.execute('SELECT * FROM runner_budgets WHERE id=?',(ident,)).fetchone())

def set_default(db,body):
    ensure(db)
    if body.budget_id and not db.execute('SELECT 1 FROM runner_budgets WHERE id=?',(body.budget_id,)).fetchone():raise ServiceError(404,'预算不存在')
    with db:
        c=db.execute('UPDATE runner_budget_settings SET default_budget_id=?,revision=revision+1 WHERE id=1 AND revision=?',(body.budget_id,body.expected_revision))
        if c.rowcount!=1:raise ServiceError(409,'默认配置版本已变化，请重新载入')
    return listing(db)

def resolve(db,policy,selection=None):
    ensure(db)
    ident=selection.id if selection else db.execute('SELECT default_budget_id FROM runner_budget_settings WHERE id=1').fetchone()[0]
    resolved=dict(policy)
    resolved['budget_selection']=selection.model_dump() if selection else None
    if not ident:
        resolved['budget_snapshot']=None
        return resolved
    row=db.execute('SELECT * FROM runner_budgets WHERE id=?',(ident,)).fetchone()
    if not row:raise ServiceError(404,'预算不存在')
    if selection and row['revision']!=selection.revision:raise ServiceError(409,'预算已更新，请重新选择后发送')
    snap=BudgetSnapshot(id=ident,name=row['name'],revision=row['revision'],**json.loads(row['values_json']))
    values=snap.model_dump()
    minimum=3 if all(t in policy.get('tools',[]) for t in ['reader_guide_context','reader_guide_material','reader_guide_submit']) or policy['id']=='frontier_monitor' else int(bool(policy.get('tools')))
    if values['max_calls']<minimum:raise ServiceError(422,f'当前 Skill 至少需要 {minimum} 次工具调用')
    if minimum==3 and policy['id']!='frontier_monitor' and values['max_output_tokens']<4096:raise ServiceError(422,'结构化导读需要至少 4096 单次输出 token')
    resolved.update({k:values[k] for k in KEYS});resolved['budget_snapshot']=values
    return resolved
