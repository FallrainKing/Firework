"""Explicit, hash-confirmed history transfer; never silently resume a different provider."""
import hashlib
import json
import uuid
from pydantic import BaseModel,Field
from ..core.errors import ServiceError
from ..runner_config import connections
from ..runner_config.connection_schemas import ConnectionRef
from .service import require_session,session_view
from . import repository as repo

class Preview(BaseModel):
    connection:ConnectionRef|None=None
    include_history:bool=False
    max_turns:int=Field(10,ge=1,le=20)

class Confirm(Preview):
    confirmation_hash:str=Field(pattern='^[a-f0-9]{64}$')

def preview(state,ident,body):
    db=state.db;row=require_session(db,ident)
    if row['execution_mode']=='terminal' and body.include_history:raise ServiceError(409,'终端记录尚不支持历史转移，可创建不带历史的分支')
    snap=connections.snapshot(db,state.settings,body.connection)
    history=[];run_ids=[]
    if body.include_history:
        runs=db.execute("SELECT * FROM agent_runs WHERE conversation_id=? AND status='succeeded' ORDER BY rowid DESC LIMIT ?",(ident,body.max_turns)).fetchall()
        for r in reversed(runs):
            history.extend([{'role':'user','content':r['prompt']},{'role':'assistant','content':r['answer']}]);run_ids.append(r['id'])
    encoded=json.dumps(history,ensure_ascii=False)
    if len(encoded)>100000:raise ServiceError(422,'选定历史过长，请减少轮次或创建不带历史的分支')
    plan={'source_session_id':ident,'paper_ids':repo.paper_ids(db,ident),'connection':snap,'history':history,'run_ids':run_ids,'skill':row['skill'],'skill_version_id':row['skill_version_id'],'entry_context':row['entry_context']}
    digest=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return plan|{'confirmation_hash':digest,'model_called':False}

def create(state,ident,body):
    db=state.db;plan=preview(state,ident,body)
    if body.confirmation_hash!=plan['confirmation_hash']:raise ServiceError(409,'转移内容或目标已变化，请重新预览')
    old=db.execute('SELECT conversation_id FROM conversation_seeds WHERE source_session_id=? AND transfer_hash=?',(ident,plan['confirmation_hash'])).fetchone()
    if old:return {'session':session_view(db,require_session(db,old[0])),'model_called':False,'reused':True}
    original=require_session(db,ident)
    with db:
        cur=repo.insert_session(db,title=original['title'][:140]+' · 分支',kind=original['kind'],skill=plan['skill'],template_id=original['template_id'],category_id=original['category_id'],native_session_id=str(uuid.uuid4()),draft_prompt='',skill_version_id=plan['skill_version_id'])
        sid=cur.lastrowid
        db.execute('UPDATE conversations SET parent_session_id=?,runner_connection_json=?,entry_context=? WHERE id=?',(ident,json.dumps(plan['connection']),plan['entry_context'],sid))
        repo.link_papers(db,sid,plan['paper_ids'])
        db.execute('INSERT INTO conversation_seeds(conversation_id,source_session_id,history_json,transfer_hash) VALUES (?,?,?,?)',(sid,ident,json.dumps(plan['history'],ensure_ascii=False),plan['confirmation_hash']))
    return {'session':session_view(db,require_session(db,sid)),'model_called':False}
