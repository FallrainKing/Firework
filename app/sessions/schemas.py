"""Request models for the sessions API."""
from pydantic import BaseModel, Field


class Name(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SessionCreate(BaseModel):
    title: str = Field('', max_length=160)
    template_id: str = 'chat'
    starting_prompt: str | None = Field(None, max_length=3000)
    category_id: int | None = None
    paper_ids: list[int] = Field(default_factory=list, max_length=10)


class SessionPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=160)
    category_id: int | None = None
    archived: bool | None = None
    pinned: bool | None = None


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field('', max_length=400)
    skill: str
    prompt: str = Field('', max_length=3000)
