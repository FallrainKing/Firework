"""Request models for the paper library."""
from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = Field(None, ge=1)


class CollectionEdit(CollectionCreate):
    expected_revision: int = Field(ge=1)


class CollectionRevision(BaseModel):
    expected_revision: int = Field(ge=1)


class PaperPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    authors: list[str] | None = Field(None, max_length=100)
    affiliations: list[str] | None = Field(None, max_length=20)
    brief_summary: str | None = Field(None, max_length=4000)
    collection_ids: list[int] | None = Field(None, max_length=50)
    metadata_version: int = Field(ge=1)
    confirm_affiliations: bool = False
