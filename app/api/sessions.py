"""Task sessions, classifications and editable starting templates."""
import json
import sqlite3
import uuid
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from ..agent_catalog import KINDS, SKILLS

router=APIRouter(prefix='/api/sessions',tags=['sessions'])

def require_session(db, session_id):
    row=db.execute("SELECT * FROM conversations WHERE id=? AND module='agent'",(session_id,)).fetchone()
    if row is None:raise HTTPException(404,'会话不存在')
    return row

def session_view(db,row):
    out={k:row[k] for k in ('id','title','kind','skill','category_id','template_id','native_session_id','native_ready','archived','pinned','draft_prompt','created_at','updated_at')}
    out['paper_ids']=[r[0] for r in db.execute('SELECT paper_id FROM conversation_papers WHERE conversation_id=? ORDER BY paper_id',(row['id'],))]
    out['run_count']=db.execute('SELECT count(*) FROM agent_runs WHERE conversation_id=?',(row['id'],)).fetchone()[0]
    last=db.execute('SELECT status,answer,prompt FROM agent_runs WHERE conversation_id=? ORDER BY rowid DESC LIMIT 1',(row['id'],)).fetchone()
    out['last_status']=last['status'] if last else 'draft'
    out['preview']=(last['answer'] or last['prompt'])[:160] if last else ''
    return out

class Name(BaseModel):
    name:str=Field(min_length=1,max_length=80)

class SessionCreate(BaseModel):
    title:str=Field('',max_length=160)
    template_id:str='chat'
    starting_prompt:str|None=Field(None,max_length=3000)
    category_id:int|None=None
    paper_ids:list[int]=Field(default_factory=list,max_length=10)

class SessionPatch(BaseModel):
    title:str|None=Field(None,min_length=1,max_length=160)
    category_id:int|None=None
    archived:bool|None=None
    pinned:bool|None=None

class TemplateCreate(BaseModel):
    name:str=Field(min_length=1,max_length=80)
    description:str=Field('',max_length=400)
    skill:str
    prompt:str=Field('',max_length=3000)

@router.get('/templates')
async def templates(request:Request):
    return {'templates':[dict(r) for r in request.app.state.db.execute('SELECT * FROM task_templates ORDER BY builtin DESC,rowid')], 'kinds':KINDS,'skills':[{ 'id':k,'name':v['name']} for k,v in SKILLS.items()]}

@router.post('/templates',status_code=201)
async def create_template(body:TemplateCreate,request:Request):
    if body.skill not in SKILLS:raise HTTPException(400,'未知 Skill')
    if not body.name.strip():raise HTTPException(400,'模板名称不能为空')
    db=request.app.state.db;ident='custom_'+uuid.uuid4().hex
    db.execute('INSERT INTO task_templates(id,name,description,kind,skill,prompt) VALUES (?,?,?,?,?,?)',(ident,body.name.strip(),body.description,'custom',body.skill,body.prompt));db.commit()
    return dict(db.execute('SELECT * FROM task_templates WHERE id=?',(ident,)).fetchone())

@router.get('/categories')
async def categories(request:Request):
    return {'categories':[dict(r) for r in request.app.state.db.execute("SELECT s.id,s.name,(SELECT count(*) FROM conversations c WHERE c.category_id=s.id AND c.module='agent' AND c.archived=0) AS count FROM session_categories s ORDER BY s.id")]}

@router.post('/categories',status_code=201)
async def create_category(body:Name,request:Request):
    if not body.name.strip():raise HTTPException(400,'分类名称不能为空')
    db=request.app.state.db
    try:
        cur=db.execute('INSERT INTO session_categories(name) VALUES (?)',(body.name.strip(),));db.commit()
    except sqlite3.IntegrityError:
        db.rollback();raise HTTPException(409,'分类名称已存在')
    return {'id':cur.lastrowid,'name':body.name.strip()}

@router.get('')
async def list_sessions(request:Request,q:str=Query('',max_length=200),kind:str|None=None,category_id:int|None=None,archived:bool=False,limit:int=Query(100,ge=1,le=200)):
    db=request.app.state.db
    sql="SELECT c.* FROM conversations c WHERE c.module='agent' AND c.archived=?";args=[int(archived)]
    if kind:sql+=' AND c.kind=?';args.append(kind)
    if category_id is not None:
        sql+=' AND '+('c.category_id IS NULL' if category_id==0 else 'c.category_id=?')
        if category_id:args.append(category_id)
    if q:
        sql+=' AND (instr(lower(c.title),lower(?))>0 OR EXISTS(SELECT 1 FROM agent_runs r WHERE r.conversation_id=c.id AND (instr(lower(r.prompt),lower(?))>0 OR instr(lower(r.answer),lower(?))>0)))';args.extend([q,q,q])
    rows=db.execute(sql+' ORDER BY c.pinned DESC,c.updated_at DESC,c.id DESC LIMIT ?',args+[limit]).fetchall()
    return {'sessions':[session_view(db,r) for r in rows]}

@router.post('',status_code=201)
async def create_session(body:SessionCreate,request:Request):
    db=request.app.state.db
    template=db.execute('SELECT * FROM task_templates WHERE id=?',(body.template_id,)).fetchone()
    if template is None:raise HTTPException(400,'模板不存在')
    if body.category_id is not None and not db.execute('SELECT 1 FROM session_categories WHERE id=?',(body.category_id,)).fetchone():raise HTTPException(400,'分类不存在')
    ids=list(dict.fromkeys(body.paper_ids))
    if template['skill'] in ('paper_read','paper_review') and not ids:raise HTTPException(400,'请选择至少一篇论文')
    if template['skill']=='paper_compare' and len(ids)<2:raise HTTPException(400,'对比会话至少选择两篇论文')
    for ident in ids:
        if not db.execute('SELECT 1 FROM papers WHERE id=?',(ident,)).fetchone():raise HTTPException(400,'关联论文不存在')
    try:
        cur=db.execute("INSERT INTO conversations(module,title,messages,kind,skill,template_id,category_id,native_session_id,draft_prompt) VALUES ('agent',?,'[]',?,?,?,?,?,?)",(body.title.strip() or template['name'],template['kind'],template['skill'],template['id'],body.category_id,str(uuid.uuid4()),body.starting_prompt if body.starting_prompt is not None else template['prompt']))
        ident=cur.lastrowid
        db.executemany('INSERT INTO conversation_papers(conversation_id,paper_id) VALUES (?,?)',[(ident,p) for p in ids]);db.commit()
    except Exception:db.rollback();raise
    return {'session':session_view(db,require_session(db,ident)),'starting_prompt':body.starting_prompt if body.starting_prompt is not None else template['prompt']}

@router.get('/{session_id}')
async def detail(session_id:int,request:Request):
    db=request.app.state.db;row=require_session(db,session_id)
    return {'session':session_view(db,row),'papers':[dict(r) for r in db.execute('SELECT p.id,p.title FROM papers p JOIN conversation_papers x ON x.paper_id=p.id WHERE x.conversation_id=?',(session_id,))]}

@router.get('/{session_id}/runs')
async def session_runs(session_id:int,request:Request,before:int|None=None,limit:int=Query(50,ge=1,le=100)):
    from .agent import view
    db=request.app.state.db;require_session(db,session_id)
    sql='SELECT rowid AS sequence,* FROM agent_runs WHERE conversation_id=?';args=[session_id]
    if before is not None:sql+=' AND rowid<?';args.append(before)
    rows=db.execute(sql+' ORDER BY rowid DESC LIMIT ?',args+[limit+1]).fetchall()
    more=len(rows)>limit;rows=rows[:limit]
    return {'runs':[view(r) for r in reversed(rows)],'has_more':more,'next_before':rows[-1]['sequence'] if rows else None}

@router.patch('/{session_id}')
async def update(session_id:int,body:SessionPatch,request:Request):
    db=request.app.state.db;require_session(db,session_id)
    active=db.execute("SELECT 1 FROM agent_runs WHERE conversation_id=? AND status IN ('queued','running')",(session_id,)).fetchone()
    if body.archived and active:raise HTTPException(409,'执行中的会话暂不能归档')
    changes=body.model_dump(exclude_unset=True)
    if changes.get('title') is not None:
        changes['title']=changes['title'].strip()
        if not changes['title']:raise HTTPException(400,'标题不能为空')
    if changes.get('category_id') is not None and not db.execute('SELECT 1 FROM session_categories WHERE id=?',(changes['category_id'],)).fetchone():raise HTTPException(400,'分类不存在')
    for key,value in changes.items():
        if value is None and key!='category_id':continue
        db.execute(f'UPDATE conversations SET {key}=? WHERE id=?',(value,session_id))
    db.commit();return session_view(db,require_session(db,session_id))
