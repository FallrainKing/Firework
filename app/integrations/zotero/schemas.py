from pydantic import BaseModel,ConfigDict,Field

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class PairStart(Strict):
    name:str=Field(min_length=1,max_length=80)
    instance_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
class PairClaim(Strict):
    pair_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    device_code:str=Field(min_length=32,max_length=100)
class Approval(Strict):user_code:str=Field(pattern=r'^[a-fA-F0-9]{8}$')
class ImportItem(Strict):
    library_key:str=Field(min_length=1,max_length=80)
    item_key:str=Field(pattern=r'^[A-Z0-9]{8}$')
    title:str=Field(min_length=1,max_length=500)
    authors:list[str]=Field(default_factory=list,max_length=100)
    abstract:str=Field('',max_length=30000)
    doi:str=Field('',max_length=250)
    arxiv_id:str=Field('',max_length=100)
    url:str=Field('',max_length=2000)
    tags:list[str]=Field(default_factory=list,max_length=100)
    collection_paths:list[list[str]]=Field(default_factory=list,max_length=50)
    raw:dict=Field(default_factory=dict)
class ExportRequest(Strict):
    device_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    paper_ids:list[int]=Field(min_length=1,max_length=30)
    request_key:str=Field(min_length=8,max_length=100)
class Ack(Strict):
    lease_token:str=Field(min_length=16,max_length=100)
    success:bool
    library_key:str=Field('',max_length=80)
    item_key:str=Field('',max_length=8)
    error:str=Field('',max_length=1000)
    attachments:dict[str,str]=Field(default_factory=dict)

class AttachmentCheck(Strict):
    library_key:str=Field(min_length=1,max_length=80)
    item_key:str=Field(pattern=r'^[A-Z0-9]{8}$')
    attachment_key:str=Field(pattern=r'^[A-Z0-9]{8}$')
    file_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
