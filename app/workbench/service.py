"""Business rules for workspace state, drafts and image attachments."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pymupdf

from ..core.errors import ServiceError
from ..reader.service import linked
from ..storage import files
from . import repository as repo
from .schemas import Draft, Workspace

MAX_IMAGE = 5 * 1024 * 1024


def attachment_view(row) -> dict:
    return dict(row) | {'url': f"/api/workbench/images/{row['id']}"}


def image_rows(db, ids, sid, paper_id=None):
    rows = []
    for ident in ids:
        r = repo.find_attachment(db, ident)
        if r is None or r['conversation_id'] != sid or (paper_id is not None and r['paper_id'] != paper_id):
            raise ServiceError(400, '图片未关联当前论文会话')
        rows.append(r)
    return rows


def recent(db) -> dict:
    return {'recent': [dict(r) for r in repo.recent_reads(db)]}


def get_workspace(db, ident: str) -> dict:
    if not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ServiceError(400, '无效工作区')
    r = repo.find_workspace(db, ident)
    return json.loads(r[0]) if r else Workspace().model_dump()


def save_workspace(db, ident: str, body: Workspace) -> dict:
    if not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ServiceError(400, '无效工作区')
    if len({t.paper_id for t in body.tabs}) != len(body.tabs):
        raise ServiceError(400, '同一论文不能重复打开')
    for t in body.tabs:
        if not repo.paper_exists(db, t.paper_id):
            raise ServiceError(400, '论文不存在')
        if t.session_id is not None:
            linked(db, t.session_id, t.paper_id)
    if body.active_paper_id is not None and body.active_paper_id not in [t.paper_id for t in body.tabs]:
        raise ServiceError(400, '活动论文未打开')
    value = body.model_dump()
    repo.upsert_workspace(db, ident, json.dumps(value))
    db.commit()
    return value


def get_draft(db, sid: int, pid: int) -> dict:
    linked(db, sid, pid)
    r = repo.find_draft(db, sid, pid)
    data = json.loads(r[0]) if r else Draft().model_dump()
    data['attachments'] = [attachment_view(a) for a in image_rows(db, data['attachment_ids'], sid, pid)]
    return data


def save_draft(db, sid: int, pid: int, body: Draft) -> dict:
    linked(db, sid, pid)
    image_rows(db, body.attachment_ids, sid, pid)
    if body.context and body.context.paper_id != pid:
        raise ServiceError(400, '选区属于其他论文')
    repo.upsert_draft(db, sid, pid, json.dumps(body.model_dump(), ensure_ascii=False))
    db.commit()
    return {'saved': True}


def upload_image(db, settings, *, data: bytes, filename: str, conversation_id: int, paper_id: int) -> dict:
    linked(db, conversation_id, paper_id)
    if len(data) > MAX_IMAGE:
        raise ServiceError(413, '图片不超过 5MB')
    try:
        mime, width, height = files.image_header(data)
        decoded = pymupdf.Pixmap(data)
        if decoded.width != width or decoded.height != height:
            raise ValueError('图片尺寸不一致')
    except (RuntimeError, OSError, ValueError) as exc:
        raise ServiceError(400, str(exc) if isinstance(exc, ValueError) else '图片无法读取，请转为 PNG 或 JPEG')
    ident = uuid.uuid4().hex
    path = files.save_attachment(settings, ident, data)
    name = Path(filename.replace('\\', '/')).name[:180]
    try:
        repo.insert_attachment(db, ident, conversation_id, paper_id, name, mime, len(data), width, height)
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return attachment_view(repo.find_attachment(db, ident))


def image_file(db, settings, ident: str):
    if not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ServiceError(404, '图片不存在')
    row = repo.find_attachment(db, ident)
    if row is None:
        raise ServiceError(404, '图片不存在')
    return files.attachment_path(settings, ident), row['mime']
