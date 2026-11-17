"""Request models for agent runs."""
import uuid

from pydantic import BaseModel, Field

from ..reader.schemas import Context


class RunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    skill: str | None = None
    conversation_id: int | None = None
    contexts: list[Context] = Field(default_factory=list, max_length=3)
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)
    purpose: str = Field('chat', pattern=r'^(chat|translate|explain)$')
    request_key: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=80)
