from __future__ import annotations

from pydantic import BaseModel, Field


class SkillInstall(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=1000)
    category_names: list[str] = Field(default_factory=list, max_length=10)
    budget_profile: str = Field(default='short', pattern='^(short|read)$')
    tags: list[str] = Field(default_factory=list, max_length=20)
    default_version: str | None = Field(default=None, max_length=40)
    skill_id: str | None = Field(default=None, max_length=120)


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category_ids: list[int] | None = None
    tags: list[str] | None = None
    status: str | None = Field(default=None, pattern='^(enabled|disabled|archived)$')


class SkillDefaultVersion(BaseModel):
    version_id: int = Field(ge=1)
    expected_revision: int | None = Field(default=None, ge=1)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=100000)


class CategoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=100000)


class SkillValidateRun(BaseModel):
    prompt: str = Field(
        '请执行一次最小技能验证，并简要说明结果。',
        min_length=1,
        max_length=1000,
    )
    request_key: str = Field(
        default_factory=lambda: __import__('uuid').uuid4().hex,
        min_length=1,
        max_length=80,
    )
