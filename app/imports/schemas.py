"""Request models for import submissions."""
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class Source(BaseModel):
    channel: Literal['auto', 'arxiv', 'doi', 'url'] = 'auto'
    value: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=80)
    collection_id: int | None = None
    target_paper_id: int | None = None
