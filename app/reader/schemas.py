"""Request models for the reader API (selection context, annotations, position)."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Context(BaseModel):
    paper_id: int
    page: int = Field(ge=1)
    file_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    quote: str = Field('', max_length=4000)
    rects: list[list[float]] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def geometry(self):
        for r in self.rects:
            if len(r) != 4 or not all(0 <= v <= 1 for v in r) or r[0] + r[2] > 1.002 or r[1] + r[3] > 1.002:
                raise ValueError('Invalid normalized geometry')
        return self


class Annotation(Context):
    kind: Literal['highlight', 'note', 'ink'] = 'highlight'
    content: str = Field('', max_length=8000)
    color: Literal['#f5d76e', '#9ed8ff', '#a9dfbf', '#f4b6d5'] = '#f5d76e'
    conversation_id: int | None = None
    points: list[list[float]] = Field(default_factory=list, max_length=2000)

    @model_validator(mode='after')
    def ink(self):
        if self.kind == 'highlight' and (not self.quote.strip() or not self.rects):
            raise ValueError('Highlight requires selected text and geometry')
        if self.kind == 'note' and not self.content.strip():
            raise ValueError('Note must not be empty')
        if self.kind == 'ink' and len(self.points) < 2:
            raise ValueError('Drawing requires points')
        if any(len(p) != 2 or not all(0 <= v <= 1 for v in p) for p in self.points):
            raise ValueError('Invalid drawing geometry')
        return self


class AnnotationPatch(BaseModel):
    content: str | None = Field(None, max_length=8000)
    color: Literal['#f5d76e', '#9ed8ff', '#a9dfbf', '#f4b6d5'] | None = None
    deleted: bool | None = None


class Position(BaseModel):
    conversation_id: int
    page: int = Field(ge=1)
    zoom: Literal['fit', '1', '1.25', '1.5', '2'] = 'fit'
    tab: Literal['outline', 'notes', 'highlights', 'translations', 'info'] = 'outline'


class Translation(Context):
    conversation_id: int


class TranslationVisibility(BaseModel):
    deleted: bool
