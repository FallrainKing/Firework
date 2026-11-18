"""Business rules for import submissions and agent-bound execution."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from pathlib import Path

from fastapi import HTTPException

from ..agent import service as agent_service
from ..core.errors import ServiceError
from ..ingest.metadata import extract_arxiv_id
from ..papers import service as papers_service
from ..sessions import service as sessions_service
from ..sessions.schemas import SessionCreate
from ..storage import files
from . import repository as repo, sources
from .pipeline import process_import
from .schemas import Source

MAX_PDF_BYTES = sources.MAX_PDF_BYTES


def import_view(row) -> dict:
    return {k: row[k] for k in ('id', 'channel', 'source_value', 'original_filename', 'status', 'paper_id', 'conversation_id', 'run_id', 'message', 'error', 'created_at')}


def validate_targets(db, collection_id, target) -> None:
    if collection_id and not papers_service.collection_exists(db, collection_id):
        raise ServiceError(400, '分类不存在')
    if target and not papers_service.paper_exists(db, target):
        raise ServiceError(400, '目标论文不存在')


async def start_import(ident: str, db, state) -> dict:
    from ..agent.schemas import RunCreate
    from ..agent.service import create_run

    row = repo.find_import(db, ident)
    if row['status'] in ('completed', 'running'):
        return import_view(row)
    if row['run_id']:
        active = agent_service.run_row(db, row['run_id'])
        if active and active['status'] in ('queued', 'running'):
            return import_view(row)
    sid = row['conversation_id']
    if sid is None:
        result = sessions_service.create_session(db, SessionCreate(template_id='import', title='导入：' + (row['original_filename'] or row['source_value'])[:100]))
        sid = result['session']['id']
        repo.set_conversation(db, ident, sid)
        db.commit()
    try:
        run = await create_run(RunCreate(conversation_id=sid, prompt=f'请执行已授权的论文入库请求 {ident}。调用 paper_import 工具一次，按工具结果告知是否取得全文，不要编造。'), state)
    except (HTTPException, ServiceError) as exc:
        repo.set_failed(db, ident, str(exc.detail)[:250])
        db.commit()
        return import_view(repo.find_import(db, ident))
    repo.set_pending(db, ident, run['id'])
    db.commit()
    return import_view(repo.find_import(db, ident))


async def submit_source(db, body: Source, state) -> dict:
    value = body.value.strip()
    channel = body.channel
    prior = repo.find_import_by_key(db, body.request_key)
    if prior:
        if prior['source_value'] != value or (channel != 'auto' and prior['channel'] != channel) or prior['collection_id'] != body.collection_id or prior['target_paper_id'] != body.target_paper_id:
            raise ServiceError(409, '请求编号已用于其他导入参数')
        return import_view(prior)
    validate_targets(db, body.collection_id, body.target_paper_id)
    try:
        if channel == 'auto':
            try:
                extract_arxiv_id(value)
                channel = 'arxiv'
            except ValueError:
                try:
                    sources.normalize_doi(value)
                    channel = 'doi'
                except ValueError:
                    channel = 'url'
        if channel == 'arxiv':
            extract_arxiv_id(value)
        elif channel == 'doi':
            sources.normalize_doi(value)
        else:
            await sources.public_url(value)
    except ValueError as e:
        raise ServiceError(400, str(e))
    ident = uuid.uuid4().hex
    repo.insert_source_import(db, ident, body.request_key, channel, value, body.collection_id, body.target_paper_id)
    db.commit()
    return await start_import(ident, db, state)


async def upload_import(db, settings, state, *, data: bytes, filename: str, request_key: str, collection_id, target_paper_id) -> dict:
    if not 1 <= len(request_key) <= 80:
        raise ServiceError(400, '无效请求编号')
    prior = repo.find_import_by_key(db, request_key)
    if prior:
        # Baseline streamed the body and hit the size cap before comparing
        # digests; keep 413 ahead of the idempotency 409.
        if len(data) > MAX_PDF_BYTES:
            raise ServiceError(413, 'PDF 超过 30MB 限额')
        digest = hashlib.sha256(data).hexdigest()
        if prior['channel'] != 'upload' or digest != prior['file_hash'] or prior['collection_id'] != collection_id or prior['target_paper_id'] != target_paper_id:
            raise ServiceError(409, '请求编号已用于其他文件或分类')
        return import_view(prior)
    validate_targets(db, collection_id, target_paper_id)
    if not filename.lower().endswith('.pdf'):
        raise ServiceError(400, '请选择 PDF 文件')
    # Baseline checked the first block's magic before the accumulated size.
    if data and not data[:1024].lstrip().startswith(b'%PDF-'):
        raise ServiceError(400, '文件不是有效 PDF')
    if len(data) > MAX_PDF_BYTES:
        raise ServiceError(413, 'PDF 超过 30MB 限额')
    if not data:
        raise ServiceError(400, 'PDF 文件为空')
    ident = uuid.uuid4().hex
    path = files.save_upload(settings, ident, data)
    try:
        repo.insert_upload_import(db, ident, request_key, Path(filename.replace('\\', '/')).name[:200], hashlib.sha256(data).hexdigest(), collection_id, target_paper_id)
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return await start_import(ident, db, state)


async def retry_import(db, ident: str, state) -> dict:
    if not repo.find_import(db, ident):
        raise ServiceError(404, '入库请求不存在')
    return await start_import(ident, db, state)


def imports_view(db) -> dict:
    return {'imports': [import_view(r) for r in repo.list_imports(db)]}


def get_import(db, ident: str) -> dict:
    row = repo.find_import(db, ident)
    if row is None:
        raise ServiceError(404, '入库请求不存在')
    out = import_view(row)
    if row['run_id']:
        run = agent_service.run_row(db, row['run_id'])
        if run and run['status'] in ('failed', 'cancelled') and row['status'] not in ('completed', 'running'):
            out.update(status='failed', error=row['error'] or run['error'])
    return out


async def execute_import(db, settings, state, *, ident: str, run_id: str, token: str) -> dict:
    token_file = settings.data_dir / 'agent' / 'internal-token'
    try:
        expected = token_file.read_text().strip()
    except OSError:
        raise ServiceError(403, 'Internal tool unavailable')
    if not hmac.compare_digest(token, expected):
        raise ServiceError(403, 'Internal tool authentication required')
    row = repo.find_import(db, ident)
    if row is None:
        raise ServiceError(404, '入库请求不存在')
    run = agent_service.run_row(db, run_id)
    if not run or run['id'] != row['run_id'] or run['conversation_id'] != row['conversation_id'] or run['skill'] != 'paper_import' or run['status'] != 'running':
        raise ServiceError(403, 'Import is not bound to this active Agent task')
    if row['status'] == 'running':
        raise ServiceError(409, '入库请求正在执行')
    repo.set_running(db, ident)
    db.commit()
    try:
        async with asyncio.timeout(80):
            result = await process_import(row, db, settings, state.embedder, state.store)
        pid = result['paper_id']
        if row['collection_id']:
            papers_service.add_to_collection(db, row['collection_id'], pid)
        sessions_service.link_paper(db, row['conversation_id'], pid)
        repo.set_completed(db, ident, pid, result['message'])
        db.commit()
        if row['channel'] == 'upload':
            files.upload_path(settings, ident).unlink(missing_ok=True)
        return result
    except Exception as exc:
        db.rollback()
        message = str(exc)[:250] if isinstance(exc, ValueError) else '来源下载或解析暂时失败：' + type(exc).__name__
        repo.set_failed(db, ident, message)
        db.commit()
        raise ServiceError(502, message)
