"""Business rules for paper cards, collections and metadata edits."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from ..core.errors import ServiceError
from . import assets, repository as repo
from .schemas import CollectionCreate, PaperPatch


def require_paper(db: sqlite3.Connection, paper_id: int):
    row = repo.find_paper(db, paper_id)
    if row is None:
        raise ServiceError(404, '论文不存在')
    return row


def paper_exists(db: sqlite3.Connection, paper_id: int) -> bool:
    return bool(repo.paper_exists(db, paper_id))


def collection_exists(db: sqlite3.Connection, collection_id: int) -> bool:
    return bool(repo.collection_exists(db, collection_id))


def add_to_collection(db: sqlite3.Connection, collection_id: int, paper_id: int) -> None:
    repo.add_collection_item(db, collection_id, paper_id)


def card(db: sqlite3.Connection, row) -> dict:
    d = dict(row)
    for k in ('authors', 'affiliations'):
        try:
            d[k] = json.loads(d[k] or '[]')
        except ValueError:
            d[k] = []
        if not isinstance(d[k], list):
            d[k] = []
    d['summary'] = d['brief_summary'] or (d['abstract'] or '')[:320]
    d['collections'] = [dict(r) for r in repo.paper_collections(db, d['id'])]
    d['thumbnail_url'] = f"/api/library/papers/{d['id']}/thumbnail" if d['pdf_path'] else None
    d['image_caption'] = '原始 PDF 首页预览' if d['pdf_path'] else '书目信息 · 全文待补充'
    d['has_pdf'] = bool(d['pdf_path'])
    d.pop('pdf_path', None)
    return d


def collections_view(db: sqlite3.Connection) -> dict:
    return {'collections': [dict(r) for r in repo.list_collections(db)]}


def create_collection(db: sqlite3.Connection, body: CollectionCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise ServiceError(400, '分类名称不能为空')
    try:
        cur = repo.insert_collection(db, name)
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise ServiceError(409, '分类名称已存在')
    return {'id': cur.lastrowid, 'name': name}


def papers_view(db, q='', collection_id=None, limit=60, offset=0) -> dict:
    total = repo.count_papers(db, q, collection_id)
    rows = repo.search_papers(db, q, collection_id, limit, offset)
    return {'papers': [card(db, r) for r in rows], 'total': total, 'offset': offset, 'has_more': offset + len(rows) < total}


def paper_detail(db: sqlite3.Connection, paper_id: int) -> dict:
    return card(db, require_paper(db, paper_id))


async def refresh_card(db: sqlite3.Connection, settings, paper_id: int) -> dict:
    row = require_paper(db, paper_id)
    try:
        await asyncio.to_thread(assets.preview_path, settings, row['pdf_path'])
        candidates = await asyncio.to_thread(assets.affiliation_candidates, settings, row['pdf_path'])
    except (ValueError, RuntimeError, OSError):
        raise ServiceError(400, '无法读取该论文原始 PDF')
    if row['affiliation_source'] != 'user':
        repo.refresh_affiliations(db, paper_id, json.dumps(candidates, ensure_ascii=False), 'pdf_first_page_unverified' if candidates else 'missing', row['metadata_version'])
        db.commit()
    return card(db, require_paper(db, paper_id))


def edit_paper(db: sqlite3.Connection, paper_id: int, body: PaperPatch) -> dict:
    row = require_paper(db, paper_id)
    if row['metadata_version'] != body.metadata_version:
        raise ServiceError(409, '论文信息已更新，请刷新后重试')
    if body.title is not None and not body.title.strip():
        raise ServiceError(400, '标题不能为空')
    for values in (body.authors, body.affiliations):
        if values is not None and any(not v.strip() or len(v) > 240 for v in values):
            raise ServiceError(400, '作者/单位字段为空或过长')
    if body.collection_ids is not None:
        for ident in body.collection_ids:
            if not repo.collection_exists(db, ident):
                raise ServiceError(400, '论文分类不存在')
    try:
        fields = body.model_dump(exclude_unset=True)
        fields.pop('metadata_version', None)
        fields.pop('confirm_affiliations', None)
        collection_ids = fields.pop('collection_ids', None)
        for key, value in fields.items():
            if value is None:
                continue
            if key in ('authors', 'affiliations'):
                value = json.dumps(value, ensure_ascii=False)
            repo.update_paper_field(db, paper_id, key, value)
        if body.affiliations is not None and (body.confirm_affiliations or body.affiliations != json.loads(row['affiliations'])):
            repo.set_affiliation_source(db, paper_id, 'user')
        if body.brief_summary is not None:
            repo.set_summary_source(db, paper_id, 'user')
        if collection_ids is not None:
            repo.replace_collection_items(db, paper_id, collection_ids)
        repo.bump_metadata_version(db, paper_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return card(db, require_paper(db, paper_id))
