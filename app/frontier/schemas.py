from typing import Literal
from pydantic import BaseModel, Field, model_validator

class TopicConfig(BaseModel):
    skill_id: str = Field('frontier_monitor',max_length=120)
    skill_version_id: int | None = Field(None,ge=1)
    goal: str = Field('', max_length=1500)
    domains: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    authors: list[str] = Field(default_factory=list, max_length=10)
    teams: list[str] = Field(default_factory=list, max_length=10)
    exclude: list[str] = Field(default_factory=list, max_length=10)
    sources: list[Literal['arxiv','crossref','github']] = Field(default_factory=lambda:['arxiv','github'], min_length=1,max_length=3)
    collection_ids: list[int] = Field(default_factory=list,max_length=10)
    interval_hours: int = Field(24,ge=1,le=8760)
    lookback_days: int = Field(30,ge=1,le=365)
    max_results: int = Field(5,ge=1,le=20)
    daily_run_limit: int = Field(4,ge=1,le=24)
    @model_validator(mode='after')
    def valid(self):
        if not any([self.goal.strip(), *[v.strip() for v in self.domains+self.keywords+self.authors+self.teams]]):
            raise ValueError('请至少填写研究目标、领域、关键词、作者或团队之一')
        for values in (self.domains,self.keywords,self.authors,self.teams,self.exclude):
            if any(not v.strip() or len(v)>200 for v in values): raise ValueError('选项不能为空或超过 200 字')
        self.sources=list(dict.fromkeys(self.sources))
        return self

class TopicCreate(BaseModel):
    title: str = Field(min_length=1,max_length=160)
    config: TopicConfig

class TopicPatch(TopicCreate):
    revision: int

class Trigger(BaseModel):
    request_key: str = Field(min_length=1,max_length=80)

class Decision(BaseModel):
    action: Literal['approve','ignore','reopen']
    revision: int
    request_key: str = Field(min_length=1,max_length=80)
    collection_ids: list[int] = Field(default_factory=list,max_length=10)
    fulltext: bool = False
    confirm_distinct: bool = False

class BatchDecision(BaseModel):
    items: list[dict] = Field(min_length=1,max_length=30)

class Report(BaseModel):
    markdown: str = Field(min_length=1,max_length=20000)
    citations: list[str] = Field(default_factory=list,max_length=60)
    reasons: dict[str,str] = Field(default_factory=dict)
