"""Public declarations; secrets are excluded from representations and dumps."""
from typing import Literal
from urllib.parse import urlsplit
import ipaddress
import re
from pydantic import BaseModel,ConfigDict,Field,SecretStr,field_validator

class ConnectionRef(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    revision:int=Field(ge=1)

class ConnectionConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    base_url:str=Field(min_length=8,max_length=500)
    model:str=Field(min_length=1,max_length=150)
    auth_type:Literal['api_key','bearer']='api_key'
    vision:Literal['unknown','declared_yes','declared_no']='unknown'
    context_window:int=Field(200000,ge=4096,le=1000000)
    role_prompt:str=Field('',max_length=6000)

    @field_validator('base_url')
    @classmethod
    def url(cls,value):
        try:
            u=urlsplit(value)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment or u.port==0:
                raise ValueError()
            if not re.fullmatch(r'[A-Za-z0-9.:-]+',u.hostname) or any(c.isspace() for c in value) or '\\' in value:
                raise ValueError()
        except ValueError:raise ValueError('请填写不含凭据、查询参数或片段的 HTTP(S) API 根地址') from None
        return value.rstrip('/')

    @field_validator('model')
    @classmethod
    def model_name(cls,value):
        if not value.strip() or any(ord(c)<32 for c in value):raise ValueError('模型名称无效')
        return value.strip()

class ConnectionWrite(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=80)
    config:ConnectionConfig
    api_key:SecretStr|None=Field(None,exclude=True,repr=False)
    enabled:bool=True
    expected_revision:int|None=Field(None,ge=1)

class ConnectionSnapshot(ConnectionConfig):
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    revision:int=Field(ge=1)
    name:str=Field(min_length=1,max_length=80)

class ConnectionDefault(BaseModel):
    model_config=ConfigDict(extra='forbid')
    connection_id:str|None=None
    expected_revision:int=Field(ge=1)
