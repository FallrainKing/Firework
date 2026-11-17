"""Request models for research schedules."""
from pydantic import BaseModel, Field


class Schedule(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    conversation_id: int
    prompt: str = Field(min_length=1, max_length=3000)
    interval_hours: int = Field(24, ge=1, le=8760)
    enabled: bool = False


class Enable(BaseModel):
    enabled: bool
