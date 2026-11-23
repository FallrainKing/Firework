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


def validate_context(settings, db, context, conversation_id=None):
    if conversation_id is not None and not repo.is_linked(db, conversation_id, context['paper_id']):
        raise ValueError('论文未关联当前会话')
    row = repo.find_paper(db, context['paper_id'])
    if row is None:
        raise ValueError('论文不存在')
    data = pages.read_page(settings, row, context['page'])
    if data['file_version'] != context['file_version']:
        raise ValueError('PDF 版本已变化，请重新选择原文')
    quote = context.get('quote', '').strip()
    # PDF.js and PyMuPDF can differ in ligatures/hyphens/reading order.
    # Preserve captured geometry, but never overstate a failed text match.
    located = bool(quote and pages.normalize(quote) in pages.normalize(data['text']))
    return {**context, 'quote': quote, 'validation': 'text_located' if located else 'page_captured', 'source': 'original_pdf_page'}


def annotation_view(row) -> dict:
    out = dict(row)
    out['rects'] = json.loads(out.pop('rects_json'))
    out['points'] = json.loads(out.pop('points_json'))
    return out


def annotations(db: sqlite3.Connection, paper_id: int) -> dict:
    paper(db, paper_id)
    return {'annotations': [annotation_view(r) for r in repo.list_annotations(db, paper_id)]}


def insert_annotation_record(db,body:Annotation):
    """Shared insert primitive; caller owns validation and transaction boundary."""
    ident=uuid.uuid4().hex
    repo.insert_annotation(db,ident,body.paper_id,body.conversation_id,body.file_version,body.page,body.kind,body.quote,body.content,body.color,json.dumps(body.rects),json.dumps(body.points))
    return ident


def annotate(db: sqlite3.Connection, settings, body: Annotation) -> dict:
    try:
        ctx = validate_context(settings, db, body.model_dump(include={'paper_id', 'page', 'file_version', 'quote', 'rects'}), body.conversation_id)
    except ValueError as e:
        raise ServiceError(409, str(e))
    ident = insert_annotation_record(db,body)
    db.execute("UPDATE reader_annotations SET document_version_id=(SELECT v.id FROM document_versions v JOIN paper_documents d ON d.id=v.document_id WHERE d.paper_id=? AND v.file_hash=? ORDER BY d.role LIMIT 1) WHERE id=?", (body.paper_id, body.file_version, ident))
    db.commit()
    return {**annotation_view(repo.find_annotation(db, ident)), 'validation': ctx['validation']}


def edit_annotation(db: sqlite3.Connection, ident: str, body: AnnotationPatch) -> dict:
    row = repo.find_annotation(db, ident)
    if row is None:
        raise ServiceError(404, '批注不存在')
    if row['origin']=='ai' and (body.content is not None or body.color is not None):
        raise ServiceError(409,'请先采纳为个人批注再编辑；AI 原始批注可以移除或恢复')
    if row['kind'] == 'note' and body.content is not None and not body.content.strip():
        raise ServiceError(400, '批注不能为空')
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            repo.update_annotation_field(db, ident, key, value)
    db.commit()
    return annotation_view(repo.find_annotation(db, ident))


def get_state(db: sqlite3.Connection, sid: int, pid: int,file_version=None) -> dict:
    linked(db, sid, pid)
    version=db.execute('SELECT v.file_hash FROM papers p JOIN document_versions v ON v.id=p.default_version_id WHERE p.id=?',(pid,)).fetchone()
    if file_version:
        if not db.execute('SELECT 1 FROM document_versions v JOIN paper_documents d ON d.id=v.document_id WHERE d.paper_id=? AND v.file_hash=?',(pid,file_version)).fetchone():raise ServiceError(404,'原文版本不存在')
        version=(file_version,)
    row=db.execute('SELECT * FROM version_reader_states WHERE conversation_id=? AND paper_id=? AND file_version=?',(sid,pid,version[0])).fetchone() if version else repo.find_state(db,sid,pid)
    return dict(row) if row else {'page': 1, 'zoom': 'fit', 'tab': 'outline'}


async def save_state(db: sqlite3.Connection, settings, paper_id: int, body: Position) -> dict:
    linked(db, body.conversation_id, paper_id)
    try:
        row=paper(db,paper_id)
        if body.file_version:
            from ..documents import service as documents
            v=db.execute('SELECT v.id FROM document_versions v JOIN paper_documents d ON d.id=v.document_id WHERE d.paper_id=? AND v.file_hash=?',(paper_id,body.file_version)).fetchone()
            if v:
                version=documents.version(db,paper_id,v[0]);row=dict(row)|{'pdf_path':str(documents.asset_path(settings,version['storage_key']))}
        doc = await asyncio.to_thread(pages.document_info, settings, row)
    except ValueError as e:
        raise ServiceError(400, str(e))
    if body.file_version and body.file_version!=doc['file_version']:raise ServiceError(409,'保存位置时文件版本已变化，请刷新')
    if body.page > doc['page_count']:
        raise ServiceError(400, '页码超出范围')
    db.execute('INSERT INTO version_reader_states(conversation_id,paper_id,file_version,page,zoom,tab) VALUES (?,?,?,?,?,?) ON CONFLICT(conversation_id,paper_id,file_version) DO UPDATE SET page=excluded.page,zoom=excluded.zoom,tab=excluded.tab,updated_at=CURRENT_TIMESTAMP',(body.conversation_id,paper_id,doc['file_version'],body.page,body.zoom,body.tab))
    repo.upsert_state(db, body.conversation_id, paper_id, body.page, body.zoom, body.tab)
    db.commit()
    return body.model_dump(exclude_none=True)


def translations(db: sqlite3.Connection, paper_id: int) -> dict:
    from ..agent import service as agent_service  # late import: agent.service imports this module

    paper(db, paper_id)
    rows = repo.list_translations(db, paper_id)
    runs = agent_service.runs_by_ids(db, [r['run_id'] for r in rows])
    external=[dict(r)|{'rects':json.loads(r['rects_json']),'run_id':None,'conversation_id':None,'error':None,'origin':'external'} for r in db.execute('SELECT * FROM reader_external_translations WHERE paper_id=? AND deleted=0 ORDER BY created_at DESC',(paper_id,))]
    return {'translations': [{**dict(r), **runs[r['run_id']], 'rects':json.loads(r['anchor_json']).get('rects',[])} for r in rows]+external}


async def translate(db: sqlite3.Connection, settings, body: Translation, state) -> dict:
    from ..agent.schemas import RunCreate
    from ..agent.service import create_run

    linked(db, body.conversation_id, body.paper_id)
    if not body.quote.strip():
        raise ServiceError(400, '请先选择需要翻译的原文')
    try:
        context = validate_context(settings, db, body.model_dump(exclude={'conversation_id'}), body.conversation_id)
    except ValueError as e:
        raise ServiceError(409, str(e))
    digest = str(body.page) + ':' + hashlib.sha256(body.quote.strip().encode()).hexdigest()
    row = repo.find_cached_translation(db, body.paper_id, body.file_version, digest, 'zh-CN')
    old = None
    if row:
        from ..agent import service as agent_service

        run = agent_service.runs_by_ids(db, [row['run_id']])[row['run_id']]
        old = {**dict(row), 'status': run['status'], 'answer': run['answer']}
    if old and old['status'] not in ('failed', 'cancelled'):
        repo.undelete_translation(db, old['id'])
        db.commit()
        return {**old, 'deleted': 0, 'cached': True}
    run = await create_run(RunCreate(conversation_id=body.conversation_id, prompt='请把本次选中的原文准确翻译成简体中文，只输出译文，保留专业术语、数字与公式。', contexts=[context], purpose='translate'), state)
    ident = old['id'] if old else uuid.uuid4().hex
    repo.upsert_translation(db, ident, body.paper_id, body.conversation_id, body.page, body.file_version, body.quote, digest, run['id'])
    db.execute('UPDATE reader_translations SET anchor_json=? WHERE id=?',(json.dumps({'rects':body.rects}),ident))
    db.commit()
    return {'id': ident, 'run_id': run['id'], 'status': run['status'], 'cached': False}


def set_translation_visibility(db: sqlite3.Connection, ident: str, body: TranslationVisibility) -> dict:
    external=db.execute('SELECT 1 FROM reader_external_translations WHERE id=?',(ident,)).fetchone()
    if external:
        with db:db.execute('UPDATE reader_external_translations SET deleted=? WHERE id=?',(int(body.deleted),ident))
        return {'id':ident,'deleted':body.deleted}
    if not repo.translation_exists(db, ident):
        raise ServiceError(404, '翻译记录不存在')
    repo.set_translation_deleted(db, ident, body.deleted)
    db.commit()
    return {'id': ident, 'deleted': body.deleted}
