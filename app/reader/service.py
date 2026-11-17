"""Business rules for reader evidence, annotations, position and translations."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import uuid

from ..core.errors import ServiceError
from ..sessions.service import require_session
from . import pages, repository as repo
from .schemas import Annotation, AnnotationPatch, Position, Translation, TranslationVisibility


def paper(db: sqlite3.Connection, ident: int):
    row = repo.find_paper(db, ident)
    if row is None:
        raise ServiceError(404, '论文不存在')
    return row


def linked(db: sqlite3.Connection, sid: int, pid: int) -> None:
    require_session(db, sid)
    if not repo.is_linked(db, sid, pid):
        raise ServiceError(400, '当前会话未关联该论文')


def annotation_view(row) -> dict:
    out = dict(row)
    out['rects'] = json.loads(out.pop('rects_json'))
    out['points'] = json.loads(out.pop('points_json'))
    return out


def annotations(db: sqlite3.Connection, paper_id: int) -> dict:
    paper(db, paper_id)
    return {'annotations': [annotation_view(r) for r in repo.list_annotations(db, paper_id)]}


def annotate(db: sqlite3.Connection, settings, body: Annotation) -> dict:
    try:
        ctx = pages.validate_context(settings, db, body.model_dump(include={'paper_id', 'page', 'file_version', 'quote', 'rects'}), body.conversation_id)
    except ValueError as e:
        raise ServiceError(409, str(e))
    ident = uuid.uuid4().hex
    repo.insert_annotation(db, ident, body.paper_id, body.conversation_id, body.file_version, body.page, body.kind, body.quote, body.content, body.color, json.dumps(body.rects), json.dumps(body.points))
    db.commit()
    return {**annotation_view(repo.find_annotation(db, ident)), 'validation': ctx['validation']}


def edit_annotation(db: sqlite3.Connection, ident: str, body: AnnotationPatch) -> dict:
    row = repo.find_annotation(db, ident)
    if row is None:
        raise ServiceError(404, '批注不存在')
    if row['kind'] == 'note' and body.content is not None and not body.content.strip():
        raise ServiceError(400, '批注不能为空')
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            repo.update_annotation_field(db, ident, key, value)
    db.commit()
    return annotation_view(repo.find_annotation(db, ident))


def get_state(db: sqlite3.Connection, sid: int, pid: int) -> dict:
    linked(db, sid, pid)
    row = repo.find_state(db, sid, pid)
    return dict(row) if row else {'page': 1, 'zoom': 'fit', 'tab': 'outline'}


async def save_state(db: sqlite3.Connection, settings, paper_id: int, body: Position) -> dict:
    linked(db, body.conversation_id, paper_id)
    try:
        doc = await asyncio.to_thread(pages.document_info, settings, paper(db, paper_id))
    except ValueError as e:
        raise ServiceError(400, str(e))
    if body.page > doc['page_count']:
        raise ServiceError(400, '页码超出范围')
    repo.upsert_state(db, body.conversation_id, paper_id, body.page, body.zoom, body.tab)
    db.commit()
    return body.model_dump()


def translations(db: sqlite3.Connection, paper_id: int) -> dict:
    paper(db, paper_id)
    return {'translations': [dict(r) for r in repo.list_translations(db, paper_id)]}


async def translate(db: sqlite3.Connection, settings, body: Translation, request) -> dict:
    # Transitional: create_run takes (body, request) until Task 4 switches it
    # to (body, state); this signature follows in Task 4.
    from ..api.agent import RunCreate, create_run

    linked(db, body.conversation_id, body.paper_id)
    if not body.quote.strip():
        raise ServiceError(400, '请先选择需要翻译的原文')
    try:
        context = pages.validate_context(settings, db, body.model_dump(exclude={'conversation_id'}), body.conversation_id)
    except ValueError as e:
        raise ServiceError(409, str(e))
    digest = str(body.page) + ':' + hashlib.sha256(body.quote.strip().encode()).hexdigest()
    old = repo.find_cached_translation(db, body.paper_id, body.file_version, digest, 'zh-CN')
    if old and old['status'] != 'failed':
        repo.undelete_translation(db, old['id'])
        db.commit()
        return {**dict(old), 'deleted': 0, 'cached': True}
    run = await create_run(RunCreate(conversation_id=body.conversation_id, prompt='请把本次选中的原文准确翻译成简体中文，只输出译文，保留专业术语、数字与公式。', contexts=[context], purpose='translate'), request)
    ident = old['id'] if old else uuid.uuid4().hex
    repo.upsert_translation(db, ident, body.paper_id, body.conversation_id, body.page, body.file_version, body.quote, digest, run['id'])
    db.commit()
    return {'id': ident, 'run_id': run['id'], 'status': run['status'], 'cached': False}


def set_translation_visibility(db: sqlite3.Connection, ident: str, body: TranslationVisibility) -> dict:
    if not repo.translation_exists(db, ident):
        raise ServiceError(404, '翻译记录不存在')
    repo.set_translation_deleted(db, ident, body.deleted)
    db.commit()
    return {'id': ident, 'deleted': body.deleted}
