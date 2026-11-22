"""Caller-supplied research is evidence to review, never a server-verified search."""
import json
import re
import uuid
from datetime import datetime,timezone
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator
from urllib.parse import urlsplit
from ..core.errors import ServiceError
from ..frontier import service as frontier,identity
from ..frontier.schemas import TopicCreate,TopicConfig,Report

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class ExternalTopic(Strict):
    title:str=Field(min_length=1,max_length=160)
    config:TopicConfig
class Metadata(Strict):
    kind:Literal['paper','project']
    title:str=Field(min_length=1,max_length=500)
    url:str=Field(min_length=8,max_length=1500)
    doi:str|None=Field(None,max_length=300)
    arxiv_id:str|None=Field(None,max_length=100)
    authors:list[str]=Field(default_factory=list,max_length=100)
    abstract:str=Field('',max_length=12000)
    description:str=Field('',max_length=4000)
    published:str|None=Field(None,max_length=50)
    evidence_level:Literal['metadata','abstract']='metadata'
    @field_validator('url')
    @classmethod
    def public_url(cls,v):
        u=urlsplit(v)
        if u.scheme!='https' or not u.hostname or u.username or u.password or any(c.isspace() for c in v):raise ValueError('来源链接必须为不含凭据的 HTTPS URL')
        return v
    @model_validator(mode='after')
    def valid(self):
        if not self.title.strip() or any(not a.strip() or len(a)>240 for a in self.authors):raise ValueError('题名/作者无效')
        identity.identifiers(self.model_dump())
        return self
class Discovery(Strict):
    ref:str=Field(pattern=r'^[A-Za-z0-9_-]{1,60}$')
    metadata:Metadata
class Search(Strict):
    source:Literal['arxiv','crossref','github']
    query:str=Field(min_length=1,max_length=200)
    status:Literal['complete','partial','failed']
    records:list[Discovery]=Field(default_factory=list,max_length=20)
    @model_validator(mode='after')
    def valid(self):
        if self.status=='failed' and self.records:raise ValueError('失败检索不能包含结果')
        if any((r.metadata.kind=='project')!=(self.source=='github') for r in self.records):raise ValueError('来源与论文/项目类型不一致')
        return self
class Submission(Strict):
    topic_revision:int=Field(ge=1)
    producer:str=Field(min_length=1,max_length=100)
    window_start:datetime
    window_end:datetime
    markdown:str=Field(min_length=1,max_length=20000)
    searches:list[Search]=Field(min_length=1,max_length=6)
    citations:list[str]=Field(default_factory=list,max_length=60)
    reasons:dict[str,str]=Field(default_factory=dict,max_length=60)
    @model_validator(mode='after')
    def valid(self):
        if not self.producer.strip() or not self.markdown.strip():raise ValueError('来源与报告不能为空')
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None or self.window_end<self.window_start:raise ValueError('时间范围需要时区且不能倒置')
        refs=[r.ref for s in self.searches for r in s.records]
        if len(refs)!=len(set(refs)) or len(refs)>60:raise ValueError('发现引用必须唯一且最多60条')
        mentioned=set(re.findall(r'\[证据[:：]([^\]]+)\]',self.markdown))
        if not (set(self.citations)|set(self.reasons)|mentioned)<=set(refs):raise ValueError('引用不在本次提交中')
        if refs and not self.citations:raise ValueError('有发现内容时需要引用')
        if any(len(v)>1200 for v in self.reasons.values()):raise ValueError('推荐理由过长')
        return self

def submit(db,topic_id,body,token_id):
    topic=frontier.require(db,'frontier_topics',topic_id)
    if topic['revision']!=body.topic_revision:raise ServiceError(409,'主题配置已更新，请重新读取后合并',code='topic_conflict')
    cfg=json.loads(topic['config_json'])
    if any(s.source not in cfg['sources'] or len(s.records)>cfg['max_results'] for s in body.searches):raise ServiceError(422,'来源或条数超出主题配置')
    ident=uuid.uuid4().hex
    provenance={'producer':body.producer,'token_id':token_id,'verification':'caller_supplied','server_model_called':False}
    start=body.window_start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S');end=body.window_end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    db.execute("INSERT INTO frontier_runs(id,topic_id,revision,config_json,request_key,status,window_start,window_end,origin,external_provenance_json) VALUES (?,?,?,?,?,'partial',?,?,'external',?)",(ident,topic_id,topic['revision'],topic['config_json'],'external:'+ident,start,end,frontier.dump(provenance)))
    r=frontier.require(db,'frontier_runs',ident);mapping={}
    for search in body.searches:
        records=[d.metadata.model_dump(exclude_none=True)|{'external_ref':d.ref,'verification':'caller_supplied'} for d in search.records]
        result=frontier.ingest(db,r,search.source,search.query,{'records':records,'total':len(records),'truncated':search.status=='partial','window_start':start,'window_end':end},error='调用方报告检索失败' if search.status=='failed' else None)
        mapping.update({item['metadata']['external_ref']:item['evidence_id'] for item in result['items']})
    markdown=re.sub(r'\[证据[:：]([^\]]+)\]',lambda m:'[证据:'+mapping[m[1]]+']',body.markdown)
    report=Report(markdown=markdown,citations=[mapping[x] for x in body.citations],reasons={mapping[k]:v for k,v in body.reasons.items()})
    frontier.save_report(db,r,report)
    status='succeeded' if set(cfg['sources'])<={s.source for s in body.searches} and all(s.status=='complete' for s in body.searches) else 'partial'
    db.execute('UPDATE frontier_runs SET status=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',(status,ident))
    db.execute('INSERT INTO frontier_reports(run_id,version,body_md,citations_json) VALUES (?,1,?,?)',(ident,markdown,frontier.dump(report.citations)))
    # External uploads never advance trusted source watermarks or approve library imports.
    return {'saved':True,'run':frontier.run_view(db,frontier.require(db,'frontier_runs',ident)),'evidence_ids':mapping,'verification':'caller_supplied','model_called':False}
