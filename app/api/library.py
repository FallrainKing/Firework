"""Paper cards, collection membership and user-editable metadata."""
import asyncio
import json
import sqlite3
from fastapi import APIRouter,HTTPException,Query,Request
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from ..library_assets import preview_path,affiliation_candidates

router=APIRouter(prefix='/api/library',tags=['library'])

def require_paper(db,paper_id):
    row=db.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
    if row is None:raise HTTPException(404,'论文不存在')
    return row

def card(db,row):
    d=dict(row)
    for k in ('authors','affiliations'):
        try:d[k]=json.loads(d[k] or '[]')
        except ValueError:d[k]=[]
        if not isinstance(d[k],list):d[k]=[]
    d['summary']=d['brief_summary'] or (d['abstract'] or '')[:320]
    d['collections']=[dict(r) for r in db.execute('SELECT c.id,c.name FROM paper_collections c JOIN paper_collection_items x ON x.collection_id=c.id WHERE x.paper_id=? ORDER BY c.id',(d['id'],))]
    d['thumbnail_url']=f"/api/library/papers/{d['id']}/thumbnail" if d['pdf_path'] else None
    d['image_caption']='原始 PDF 首页预览' if d['pdf_path'] else '书目信息 · 全文待补充'
    d['has_pdf']=bool(d['pdf_path'])
    d.pop('pdf_path',None)
    return d

class CollectionCreate(BaseModel):
    name:str=Field(min_length=1,max_length=80)

class PaperPatch(BaseModel):
    title:str|None=Field(None,min_length=1,max_length=500)
    authors:list[str]|None=Field(None,max_length=100)
    affiliations:list[str]|None=Field(None,max_length=20)
    brief_summary:str|None=Field(None,max_length=4000)
    collection_ids:list[int]|None=Field(None,max_length=50)
    metadata_version:int=Field(ge=1)
    confirm_affiliations:bool=False

@router.get('/collections')
async def collections(request:Request):
    return {'collections':[dict(r) for r in request.app.state.db.execute('SELECT c.*,(SELECT count(*) FROM paper_collection_items x WHERE x.collection_id=c.id) AS count FROM paper_collections c ORDER BY c.id')]}

@router.post('/collections',status_code=201)
async def create_collection(body:CollectionCreate,request:Request):
    name=body.name.strip()
    if not name:raise HTTPException(400,'分类名称不能为空')
    db=request.app.state.db
    try:cur=db.execute('INSERT INTO paper_collections(name) VALUES (?)',(name,));db.commit()
    except sqlite3.IntegrityError:db.rollback();raise HTTPException(409,'分类名称已存在')
    return {'id':cur.lastrowid,'name':name}

@router.get('/papers')
async def papers(request:Request,q:str=Query('',max_length=200),collection_id:int|None=None,limit:int=Query(60,ge=1,le=100),offset:int=Query(0,ge=0)):
    db=request.app.state.db
    where=" WHERE (instr(lower(coalesce(p.title,'')),lower(?))>0 OR instr(lower(coalesce(p.abstract,'')),lower(?))>0 OR instr(lower(coalesce(p.authors,'')),lower(?))>0 OR instr(lower(p.affiliations),lower(?))>0 OR instr(lower(p.brief_summary),lower(?))>0)";args=[q]*5
    if collection_id is not None:
        if collection_id==0:where+=' AND NOT EXISTS (SELECT 1 FROM paper_collection_items x WHERE x.paper_id=p.id)'
        else:where+=' AND EXISTS(SELECT 1 FROM paper_collection_items x WHERE x.paper_id=p.id AND x.collection_id=?)';args.append(collection_id)
    total=db.execute('SELECT count(*) FROM papers p'+where,args).fetchone()[0]
    rows=db.execute('SELECT p.* FROM papers p'+where+' ORDER BY p.id DESC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    return {'papers':[card(db,r) for r in rows],'total':total,'offset':offset,'has_more':offset+len(rows)<total}

@router.get('/papers/{paper_id}')
async def paper_detail(paper_id:int,request:Request):
    db=request.app.state.db;return card(db,require_paper(db,paper_id))

@router.get('/papers/{paper_id}/thumbnail')
async def thumbnail(paper_id:int,request:Request):
    row=require_paper(request.app.state.db,paper_id)
    try:path=await asyncio.to_thread(preview_path,request.app.state.settings,row['pdf_path'])
    except (ValueError,RuntimeError,OSError):raise HTTPException(404,'PDF 预览不可用')
    return FileResponse(path,media_type='image/png',headers={'Cache-Control':'private, max-age=3600'})

@router.post('/papers/{paper_id}/refresh-card')
async def refresh(paper_id:int,request:Request):
    db=request.app.state.db;row=require_paper(db,paper_id)
    try:
        await asyncio.to_thread(preview_path,request.app.state.settings,row['pdf_path'])
        candidates=await asyncio.to_thread(affiliation_candidates,request.app.state.settings,row['pdf_path'])
    except (ValueError,RuntimeError,OSError):raise HTTPException(400,'无法读取该论文原始 PDF')
    if row['affiliation_source']!='user':
        db.execute("UPDATE papers SET affiliations=?,affiliation_source=?,metadata_version=metadata_version+1 WHERE id=? AND metadata_version=?",(json.dumps(candidates,ensure_ascii=False),'pdf_first_page_unverified' if candidates else 'missing',paper_id,row['metadata_version']));db.commit()
    return card(db,require_paper(db,paper_id))

@router.patch('/papers/{paper_id}')
async def edit(paper_id:int,body:PaperPatch,request:Request):
    db=request.app.state.db;row=require_paper(db,paper_id)
    if row['metadata_version']!=body.metadata_version:raise HTTPException(409,'论文信息已更新，请刷新后重试')
    if body.title is not None and not body.title.strip():raise HTTPException(400,'标题不能为空')
    for values in (body.authors,body.affiliations):
        if values is not None and any(not v.strip() or len(v)>240 for v in values):raise HTTPException(400,'作者/单位字段为空或过长')
    if body.collection_ids is not None:
        for ident in body.collection_ids:
            if not db.execute('SELECT 1 FROM paper_collections WHERE id=?',(ident,)).fetchone():raise HTTPException(400,'论文分类不存在')
    try:
        fields=body.model_dump(exclude_unset=True);fields.pop('metadata_version',None);fields.pop('confirm_affiliations',None);collection_ids=fields.pop('collection_ids',None)
        for key,value in fields.items():
            if value is None:continue
            if key in ('authors','affiliations'):value=json.dumps(value,ensure_ascii=False)
            db.execute(f'UPDATE papers SET {key}=? WHERE id=?',(value,paper_id))
        if body.affiliations is not None and (body.confirm_affiliations or body.affiliations!=json.loads(row['affiliations'])):db.execute("UPDATE papers SET affiliation_source='user' WHERE id=?",(paper_id,))
        if body.brief_summary is not None:db.execute("UPDATE papers SET summary_source='user' WHERE id=?",(paper_id,))
        if collection_ids is not None:
            db.execute('DELETE FROM paper_collection_items WHERE paper_id=?',(paper_id,))
            db.executemany('INSERT INTO paper_collection_items(collection_id,paper_id) VALUES (?,?)',[(i,paper_id) for i in set(collection_ids)])
        db.execute('UPDATE papers SET metadata_version=metadata_version+1 WHERE id=?',(paper_id,));db.commit()
    except Exception:db.rollback();raise
    return card(db,require_paper(db,paper_id))
