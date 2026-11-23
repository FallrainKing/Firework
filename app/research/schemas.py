from typing import Literal
from pydantic import BaseModel,Field,ConfigDict

class Evidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    paper_id:int=Field(ge=1)
    document_version_id:str=Field(min_length=1,max_length=64)
    file_version:str=Field(pattern='^[a-f0-9]{64}$')
    page:int=Field(ge=1,le=300)
    quote:str=Field('',max_length=4000)

class ArtifactWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=200)
    kind:Literal['reading','review','comparison','guide','frontier','note','file']='note'
    markdown:str=Field(min_length=1,max_length=100000)
    paper_ids:list[int]=Field(default_factory=list,max_length=20)
    file_ids:list[str]=Field(default_factory=list,max_length=20)
    evidence:list[Evidence]=Field(default_factory=list,max_length=100)
    status:Literal['draft','complete','partial','failed']='draft'
    source_run_id:str|None=Field(None,pattern='^[a-f0-9]{32}$')
    producer:str=Field('user',max_length=120)
    expected_revision:int|None=Field(None,ge=1)

class ArtifactSource(BaseModel):
    model_config=ConfigDict(extra='forbid')
    artifact_id:str=Field(pattern='^[a-f0-9]{32}$')
    revision:int=Field(ge=1)

class KnowledgeWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=200)
    markdown:str=Field(min_length=1,max_length=50000)
    sources:list[ArtifactSource]=Field(min_length=1,max_length=20)
    claim_type:Literal['source','inference','personal']='inference'
    expected_revision:int|None=Field(None,ge=1)

class Transition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['publish','reject','revoke','reopen']
    expected_revision:int=Field(ge=1)
    expected_state:Literal['candidate','published','rejected','revoked']
