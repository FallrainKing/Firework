from typing import Literal,Annotated
from pydantic import BaseModel,ConfigDict,Field

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

Identifier=Annotated[str,Field(min_length=1,max_length=160)]
Markdown=Annotated[str,Field(max_length=3000)]

class TextAnchor(Strict):
    type:Literal['text']
    block_id:Identifier
    quote:str=Field(min_length=1,max_length=1500)
    prefix:str=Field('',max_length=120)
    suffix:str=Field('',max_length=120)
class BlockAnchor(Strict):
    type:Literal['block']
    block_id:Identifier
class AssetAnchor(Strict):
    type:Literal['asset']
    asset_id:Identifier
Anchor=Annotated[TextAnchor|BlockAnchor|AssetAnchor,Field(discriminator='type')]
class GuideItem(Strict):
    key:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    category:Literal['problem','contribution','method','definition','formula','figure','experiment','limitation']
    priority:Literal['essential','recommended','optional']
    title:str=Field(min_length=1,max_length=120)
    why_important_md:str=Field(max_length=1600)
    explanation_md:Markdown
    claim_type:Literal['author_claim','reported_evidence','agent_interpretation','reading_question']
    anchors:list[Anchor]=Field(min_length=1,max_length=4)
    follow_up_questions:list[Annotated[str,Field(max_length=300)]]=Field(max_length=3)
    uncertainties:list[Annotated[str,Field(max_length=300)]]=Field(max_length=4)
class Route(Strict):
    key:Identifier
    title:str=Field(max_length=120)
    goal_md:str=Field(max_length=1000)
    item_keys:list[Identifier]=Field(max_length=12)
    block_ids:list[Identifier]=Field(max_length=12)
class Summary(Strict):
    problem_md:Markdown
    approach_md:Markdown
    contributions_md:Markdown
    limitations_md:Markdown
class Coverage(Strict):
    material_ids:list[Identifier]=Field(min_length=1,max_length=120)
    scope:Literal['metadata','abstract','selected_pages','fulltext']
    figures_read:bool
    code_read:bool
    limitations:list[Annotated[str,Field(max_length=400)]]=Field(max_length=10)
class Unknown(Strict):
    path:str=Field(max_length=160)
    reason:str=Field(max_length=600)
class GuideResult(Strict):
    schema_version:Literal['paper-guide/v1']
    material_manifest_id:Identifier
    summary:Summary
    reading_route:list[Route]=Field(min_length=1,max_length=8)
    items:list[GuideItem]=Field(max_length=12)
    coverage:Coverage
    unknown_fields:list[Unknown]=Field(max_length=20)
class GuideCreate(Strict):
    confirmed:Literal[True]
    file_version:str=Field(pattern=r'^[a-f0-9]{64}$')
    request_key:str=Field(min_length=1,max_length=80)
    skill_id:str=Field('paper_guide',max_length=120)
    skill_version_id:int|None=None
    reading_goal:str=Field('理解论文重点与阅读顺序',max_length=500)
    max_items:int=Field(6,ge=1,le=10)
    max_pages:int=Field(6,ge=1,le=6)
class MaterialRequest(Strict):
    pages:list[Annotated[int,Field(ge=1)]]=Field(min_length=1,max_length=6)
class Adopt(Strict):
    request_key:str=Field(min_length=1,max_length=80)
