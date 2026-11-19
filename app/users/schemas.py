from __future__ import annotations

from pydantic import BaseModel, Field


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class PreferenceUpdate(BaseModel):
    preferences: dict[str, object] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)
