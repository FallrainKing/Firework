"""Request models for agent runs."""
import uuid

from pydantic import BaseModel, Field

from ..reader.schemas import Context
from ..runner_config.profiles import ProfileRef
from ..runner_config.budgets import BudgetRef
from ..runner_config.connection_schemas import ConnectionRef


class RunCreate(BaseModel):
    profile: ProfileRef | None = None
    budget: BudgetRef | None = None
    connection: ConnectionRef | None = None
    prompt: str = Field(min_length=1, max_length=3000)
    skill: str | None = None
    conversation_id: int | None = None
    contexts: list[Context] = Field(default_factory=list, max_length=3)
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)
    purpose: str = Field('chat', pattern=r'^(chat|translate|explain|skill-validation|frontier|guide)$')
    request_key: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=80)
