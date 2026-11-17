"""Request models for workspace state and reading drafts."""
from pydantic import BaseModel, Field

from ..reader.schemas import Context


class Tab(BaseModel):
    paper_id: int = Field(gt=0)
    session_id: int | None = None


class Layout(BaseModel):
    left_width: int = Field(235, ge=140, le=600)
    right_width: int = Field(340, ge=140, le=600)
    left_hidden: bool = False
    right_hidden: bool = False


class Workspace(BaseModel):
    layout: Layout = Field(default_factory=Layout)
    tabs: list[Tab] = Field(default_factory=list, max_length=20)
    active_paper_id: int | None = None
    view: str = Field('read', pattern=r'^(read|compare|schedules|library)$')


class Draft(BaseModel):
    prompt: str = Field('', max_length=3000)
    context: Context | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)
