"""Account-local Skill authoring, immutable publication and feature placement."""
import io
import json
from pathlib import PurePosixPath
import uuid
import zipfile
from pydantic import BaseModel,ConfigDict,Field,model_validator
from ..core.errors import ServiceError
from . import service,repository as repo
from .schemas import SkillInstall,SkillDefaultVersion
SURFACES={'reader_chat':'阅读对话','research_chat':'研究对话','compare':'论文比较','review':'论文审查','frontier':'前沿追踪','guide':'导读批注'}
DEFAULTS={'chat':['reader_chat','research_chat'],'paper_read':['reader_chat'],'paper_review':['review','reader_chat'],'paper_compare':['compare'],'frontier_monitor':['frontier'],'paper_guide':['guide'],'search_library':['research_chat','reader_chat'],'search_arxiv':['research_chat','reader_chat'],'paper_discover':['research_chat','reader_chat']}
class DraftBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    description:str=Field('',max_length=1000)
    version:str=Field('1.0.0',pattern=r'^[A-Za-z0-9._-]{1,40}$')
    instructions:str=Field(min_length=1,max_length=100000)
    resources:dict[str,str]=Field(default_factory=dict,max_length=30)
    tools:list[str]=Field(default_factory=list,max_length=13)
    surfaces:list[str]=Field(default_factory=lambda:['reader_chat'],max_length=6)
    @model_validator(mode='after')
    def valid(self):
        if not self.name.strip() or not self.instructions.strip():raise ValueError('名称与指令不能为空')
        if not set(self.tools)<=service.ALLOWED_TOOLS or len(set(self.tools))!=len(self.tools):raise ValueError('无效工具')
        if not set(self.surfaces)<=SURFACES.keys():raise ValueError('无效功能范围')
        size=len(self.instructions.encode())
        for path,content in self.resources.items():
            p=PurePosixPath(path)
            if not p.parts or str(p)!=path or p.is_absolute() or '..' in p.parts or len(p.parts)>8 or p.parts[0] not in ('references','templates') or p.suffix.lower() not in ('.md','.txt','.json','.yaml','.yml') or '\\' in path or len(path)>200:raise ValueError('资源只支持 references/ 或 templates/ 下的文本文件')
            size+=len(content.encode())
        if size>250000:raise ValueError('草稿总内容超过250KB')
        return self
class DraftWrite(DraftBody):
    expected_revision:int|None=Field(None,ge=0)
class Publish(BaseModel):
    expected_revision:int=Field(ge=1)
class Placements(BaseModel):
    surfaces:list[str]=Field(max_length=6)
    expected_revision:int=Field(ge=0)

def placements(db,sid):
    row=db.execute('SELECT * FROM skill_placements WHERE skill_id=?',(sid,)).fetchone()
    skill=repo.find_skill(db,sid)
    if not skill:raise ServiceError(404,'技能不存在')
    fallback=DEFAULTS.get(sid,[])
    if sid.startswith('custom:') and not row:
        v=repo.default_version(db,sid);tools=set(json.loads(v['manifest_json']).get('requested_tools',[])) if v else set()
        if {'reader_guide_context','reader_guide_material','reader_guide_submit'}<=tools:fallback=['guide']
        elif {'frontier_context','frontier_search','frontier_report'}<=tools:fallback=['frontier']
    return {'revision':row['revision'] if row else 0,'surfaces':json.loads(row['surfaces_json']) if row else fallback}

def set_placements(db,sid,body):
    current=placements(db,sid)
    if current['revision']!=body.expected_revision:raise ServiceError(409,'使用范围已变化，请刷新')
    if not set(body.surfaces)<=SURFACES.keys():raise ServiceError(422,'无效功能范围')
    value=json.dumps(sorted(set(body.surfaces)))
    if current['revision']:
        changed=db.execute('UPDATE skill_placements SET surfaces_json=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE skill_id=? AND revision=?',(value,sid,body.expected_revision))
    else:
        changed=db.execute('INSERT OR IGNORE INTO skill_placements(skill_id,surfaces_json) VALUES (?,?)',(sid,value))
    if changed.rowcount!=1:raise ServiceError(409,'使用范围已变化，请刷新')
    repo.audit(db,skill_id=sid,action='placements',detail_json=json.dumps({'surfaces':body.surfaces}));repo.bump_revision(db);db.commit()
    return placements(db,sid)

def compatible(db,sid,version,surface):
    if surface not in SURFACES:raise ServiceError(422,'未知功能入口')
    policy=service.execution_policy(db,sid,version)
    tools=set(policy['tools'])
    required={'guide':{'reader_guide_context','reader_guide_material','reader_guide_submit'},'frontier':{'frontier_context','frontier_search','frontier_report'}}
    if surface in required and not required[surface]<=tools:raise ServiceError(409,'该技能不具备此功能的结构化工具契约')
    special=tools & set().union(*required.values(),{'paper_import'})
    if surface not in required and special:raise ServiceError(409,'该技能需要专用任务入口')
    return policy

def available(db,surface):
    service.ensure_builtin_skills(db)
    if surface not in SURFACES:raise ServiceError(422,'未知功能入口')
    out=[]
    for r in repo.list_skills(db,limit=200):
        scope=placements(db,r['id'])
        if surface not in scope['surfaces']:continue
        item=service.view_skill(db,r['id']);reason=None
        try:compatible(db,r['id'],item['default_version_id'],surface)
        except (ValueError,ServiceError) as e:reason=str(e)
        out.append(item|{'selectable':reason is None,'blocked_reason':reason,'placements':scope})
    return {'skills':out,'surface':surface,'registry_revision':repo.latest_revision(db)}

def draft(db,settings,sid):
    skill=repo.find_skill(db,sid)
    if not skill:raise ServiceError(404,'技能不存在')
    r=db.execute('SELECT * FROM skill_drafts WHERE skill_id=?',(sid,)).fetchone()
    if r:return {'skill_id':sid,'revision':r['revision'],'published_revision':r['published_revision'],'body':json.loads(r['body_json'])}
    v=repo.default_version(db,sid)
    instructions='';resources={};tools=[]
    if v:
        policy=service.execution_policy(db,sid,v['id']) if skill['status']=='enabled' else None
        manifest=json.loads(v['manifest_json']);tools=policy['tools'] if policy else manifest.get('requested_tools',[])
        info=service.version_resources_view(db,settings,sid,v['id'])
        for f in info['resources']:
            if not f.get('readable'):continue
            resource=service.version_resource_content_view(db,settings,sid,v['id'],f['path'])
            if resource.get('truncated'):raise ServiceError(409,'资源过大，请下载原包编辑后重新导入')
            content=resource['content']
            if f['is_entry']:instructions=content
            elif f['path'].startswith(('references/','templates/')):resources[f['path']]=content
    return {'skill_id':sid,'revision':0,'published_revision':None,'body':{'name':skill['name'],'description':skill['description'],'instructions':instructions,'resources':resources,'tools':tools,'surfaces':placements(db,sid)['surfaces'],'version':('draft-'+uuid.uuid4().hex[:8])}}

def save(db,body,sid=None):
    data=DraftBody(**body.model_dump()).model_dump() if not isinstance(body,DraftWrite) else DraftBody(**body.model_dump(exclude={'expected_revision'})).model_dump()
    if sid is None:
        sid='custom:'+uuid.uuid4().hex
        repo.insert_skill(db,ident=sid,name=body.name.strip(),description=body.description,source='zip',status='disabled')
        expected=0
    else:
        skill=repo.find_skill(db,sid)
        if not skill:raise ServiceError(404,'技能不存在')
        if skill['source']=='builtin':raise ServiceError(409,'请复制内置技能后编辑指令')
        expected=body.expected_revision
        if expected is None:raise ServiceError(422,'编辑需要草稿修订号')
    current=db.execute('SELECT revision FROM skill_drafts WHERE skill_id=?',(sid,)).fetchone()
    if (current[0] if current else 0)!=expected:raise ServiceError(409,'草稿已变化，请刷新')
    value=json.dumps(data,ensure_ascii=False)
    if expected:
        changed=db.execute('UPDATE skill_drafts SET body_json=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE skill_id=? AND revision=?',(value,sid,expected))
    else:
        changed=db.execute('INSERT OR IGNORE INTO skill_drafts(skill_id,body_json) VALUES (?,?)',(sid,value))
    if changed.rowcount!=1:raise ServiceError(409,'草稿已变化，请刷新')
    repo.audit(db,skill_id=sid,action='draft.save');db.commit()
    return {'skill_id':sid,'revision':expected+1,'body':data}

def _publish(db,settings,sid,body):
    d=draft(db,settings,sid)
    if d['revision']!=body.expected_revision or not d['revision']:raise ServiceError(409,'草稿已变化，请刷新')
    data=DraftBody(**d['body'])
    if d['published_revision']==d['revision']:return service.view_skill(db,sid)
    if repo.find_version_by_skill_version(db,sid,data.version):raise ServiceError(409,'版本号已存在，请修改版本号')
    manifest={'name':data.name,'version':data.version,'description':data.description,'requested_tools':data.tools,'authoring_source':'editor'}
    buff=io.BytesIO()
    with zipfile.ZipFile(buff,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('SKILL.md',data.instructions);z.writestr('skill.json',json.dumps(manifest,ensure_ascii=False))
        for path,content in data.resources.items():z.writestr(path,content)
    report=service.import_skill_archive(db,settings,buff.getvalue(),'editor.zip')
    result=service.install_skill(db,settings,report['import_id'],SkillInstall(name=data.name,description=data.description,skill_id=sid,default_version=data.version,budget_profile='read'))
    version=result['version']['id']
    service.set_default_version(db,sid,SkillDefaultVersion(version_id=version,expected_revision=repo.find_skill(db,sid)['revision']))
    repo.update_skill_meta(db,sid,name=data.name.strip(),description=data.description)
    scope=placements(db,sid);set_placements(db,sid,Placements(surfaces=data.surfaces,expected_revision=scope['revision']))
    db.execute('UPDATE skill_drafts SET published_revision=revision WHERE skill_id=? AND revision=?',(sid,d['revision']));repo.audit(db,skill_id=sid,version_id=version,action='editor.publish');db.commit()
    return service.view_skill(db,sid)


class Atomic:
    def __init__(self,db):self.db=db
    def __getattr__(self,key):return getattr(self.db,key)
    def commit(self):pass
    def __enter__(self):return self
    def __exit__(self,*args):return False

def publish(db,settings,sid,body):
    # Async API invokes this without awaits; domain commits belong to one publication.
    service.ensure_builtin_skills(db)
    before={r[0] for r in db.execute('SELECT storage_key FROM skill_versions')}
    try:
        db.execute('BEGIN IMMEDIATE')
        result=_publish(Atomic(db),settings,sid,body)
        db.commit();return result
    except Exception:
        new=[r[0] for r in db.execute('SELECT storage_key FROM skill_versions') if r[0] not in before]
        db.rollback()
        import shutil
        for key in new:
            if key.startswith('packages/') and not db.execute('SELECT 1 FROM skill_versions WHERE storage_key=?',(key,)).fetchone():shutil.rmtree(settings.data_dir/'skills'/key,ignore_errors=True)
        raise
