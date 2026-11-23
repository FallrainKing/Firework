"""Immutable PDF assets and compatible paper-version management."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import Counter
import os
from pathlib import Path
import tempfile
import uuid

import pymupdf

from ..core.errors import ServiceError
from ..reader import pages, repository as annotation_repo, service as reader

MAX_BYTES = 50 * 1024 * 1024


def inspect_pdf(data):
    if len(data) > MAX_BYTES:
        raise ServiceError(413, 'PDF 最大支持 50 MiB')
    try:
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            if doc.is_encrypted or not 1 <= len(doc) <= 300:
                raise ValueError('仅支持未加密的 1–300 页 PDF')
            return len(doc)
    except (ValueError, RuntimeError) as e:
        raise ServiceError(400, 'PDF 无效、已加密或页数超出限制') from e


def asset_path(settings, storage_key):
    root = (settings.data_dir / 'papers').resolve()
    path = (root / storage_key).resolve()
    if path.parent != root or not path.is_file() or path.is_symlink():
        raise ServiceError(404, '原始 PDF 文件缺失')
    expected = storage_key.removeprefix('blob-').removesuffix('.pdf')
    stat = path.stat()
    if pages._fingerprint(str(path), stat.st_mtime_ns, stat.st_size) != expected:
        raise ServiceError(409, 'PDF 文件校验失败，无法使用批注')
    return path


def store_asset(db, settings, data):
    count = inspect_pdf(data)
    digest = hashlib.sha256(data).hexdigest()
    root = settings.data_dir / 'papers'
    root.mkdir(parents=True, exist_ok=True)
    owner = settings.data_dir.stat()
    if os.geteuid() == 0:
        os.chown(root, owner.st_uid, owner.st_gid)
    key = f'blob-{digest}.pdf'
    dest = root / key
    # Publish only complete bytes. Files are never overwritten with a new version.
    if dest.is_symlink():
        raise ServiceError(409, '文件存储路径异常')
    if not dest.exists():
        fd, name = tempfile.mkstemp(prefix='.document-', dir=root)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(name, dest)
            except FileExistsError:
                pass
        finally:
            Path(name).unlink(missing_ok=True)
    if dest.stat().st_size != len(data) or pages._fingerprint(str(dest), dest.stat().st_mtime_ns, dest.stat().st_size) != digest:
        raise ServiceError(409, '文件内容校验失败')
    if os.geteuid() == 0:
        os.chown(dest, owner.st_uid, owner.st_gid)
    db.execute('INSERT OR IGNORE INTO file_objects(hash,storage_key,size,page_count) VALUES (?,?,?,?)', (digest, key, len(data), count))
    return digest


def version(db, pid, vid):
    reader.paper(db, pid)
    row = db.execute('''SELECT v.*,d.paper_id,d.role,d.title AS document_title,
        f.storage_key,f.size,f.page_count FROM document_versions v
        JOIN paper_documents d ON d.id=v.document_id JOIN file_objects f ON f.hash=v.file_hash
        WHERE v.id=? AND d.paper_id=?''', (vid, pid)).fetchone()
    if not row:
        raise ServiceError(404, '文件版本不存在')
    return row


def ensure_paper(db, settings, pid):
    """Idempotently register old/imported PDF files without changing their identity."""
    paper = reader.paper(db, pid)
    if not paper['pdf_path']:
        return
    try:
        path, digest = pages.pdf_file(settings, paper)
    except (ValueError, OSError):
        return  # Keep unavailable legacy records; never attach annotations to guessed bytes.
    existing = db.execute('''SELECT v.id FROM document_versions v JOIN paper_documents d ON d.id=v.document_id
        WHERE d.paper_id=? AND d.role='main' AND v.file_hash=?''', (pid, digest)).fetchone()
    if existing:
        vid = existing['id']
    else:
        digest = store_asset(db, settings, path.read_bytes())
        doc = db.execute("SELECT id FROM paper_documents WHERE paper_id=? AND role='main'", (pid,)).fetchone()
        did = doc['id'] if doc else uuid.uuid4().hex
        if not doc:
            db.execute("INSERT INTO paper_documents(id,paper_id,role,title) VALUES (?,?,'main','正文')", (did, pid))
        vid = uuid.uuid4().hex
        db.execute('INSERT INTO document_versions(id,document_id,file_hash,label,original_filename,source) VALUES (?,?,?,?,?,?)',
                   (vid, did, digest, '原始版本', path.name, paper['source'] or 'legacy'))
        db.execute('UPDATE paper_documents SET current_version_id=? WHERE id=?', (vid, did))
    db.execute('UPDATE papers SET default_version_id=? WHERE id=?', (vid, pid))
    db.execute('UPDATE reader_annotations SET document_version_id=? WHERE paper_id=? AND file_version=? AND document_version_id IS NULL', (vid, pid, digest))
    db.execute('UPDATE conversation_papers SET file_version=? WHERE paper_id=? AND file_version IS NULL', (digest, pid))
    db.commit()


def backfill(db, settings):
    for row in db.execute('SELECT id FROM papers WHERE pdf_path IS NOT NULL').fetchall():
        try:
            ensure_paper(db, settings, row['id'])
        except (ServiceError, OSError, ValueError) as exc:
            db.rollback()
            logging.getLogger(__name__).warning('Document backfill incomplete for paper %s: %s', row['id'], exc)


def list_documents(db, settings, pid):
    ensure_paper(db, settings, pid)
    paper = reader.paper(db, pid)
    docs = []
    counts = Counter(a['file_version'] for a in annotation_repo.list_annotations(db, pid))
    for d in db.execute('SELECT * FROM paper_documents WHERE paper_id=? ORDER BY role,created_at,id', (pid,)):
        vs = []
        for v in db.execute('''SELECT v.*,f.size,f.page_count FROM document_versions v
                JOIN file_objects f ON f.hash=v.file_hash WHERE document_id=? ORDER BY v.created_at DESC,v.rowid DESC''', (d['id'],)):
            item = dict(v)
            item['available'] = (settings.data_dir / 'papers' / f"blob-{v['file_hash']}.pdf").is_file()
            item['is_default'] = v['id'] == paper['default_version_id']
            item['annotation_count'] = counts[v['file_hash']]
            item['saved_index_chunks']=db.execute('SELECT count(*) FROM document_text_chunks WHERE version_id=?',(v['id'],)).fetchone()[0]
            vs.append(item)
        docs.append({**dict(d), 'versions': vs})
    known = {v['file_hash'] for d in docs for v in d['versions']}
    missing = [{'file_hash': x['file_version'], 'count': x['n']} for x in db.execute('SELECT file_version,count(*) AS n FROM reader_annotations WHERE paper_id=? AND deleted=0 GROUP BY file_version', (pid,)) if x['file_version'] not in known]
    return {'paper_id': pid, 'title': paper['title'], 'default_version_id': paper['default_version_id'], 'documents': docs, 'unresolved_annotations': missing,'fulltext_indexed':bool(db.execute('SELECT 1 FROM chunks_meta WHERE paper_id=? LIMIT 1',(pid,)).fetchone())}


def add_version(db, settings, pid, data, *, label, filename, document_id=None, role='main', title='正文', source='', description=''):
    ensure_paper(db, settings, pid)
    if document_id and not db.execute('SELECT 1 FROM paper_documents WHERE id=? AND paper_id=?', (document_id, pid)).fetchone():
        raise ServiceError(404, '论文文档不存在')
    digest = store_asset(db, settings, data)
    if document_id:
        d = db.execute('SELECT * FROM paper_documents WHERE id=? AND paper_id=?', (document_id, pid)).fetchone()
        if not d:
            db.rollback()
            raise ServiceError(404, '论文文档不存在')
        did = d['id']
    else:
        d = db.execute("SELECT * FROM paper_documents WHERE paper_id=? AND role='main'", (pid,)).fetchone() if role == 'main' else None
        did = d['id'] if d else uuid.uuid4().hex
        if not d:
            db.execute('INSERT INTO paper_documents(id,paper_id,role,title) VALUES (?,?,?,?)', (did, pid, role, title))
    prior = db.execute('SELECT id FROM document_versions WHERE document_id=? AND file_hash=?', (did, digest)).fetchone()
    if prior:
        db.commit()
        return {'version_id': prior['id'], 'deduplicated': True}
    vid = uuid.uuid4().hex
    db.execute('INSERT INTO document_versions(id,document_id,file_hash,label,original_filename,source,description) VALUES (?,?,?,?,?,?,?)',
               (vid, did, digest, label, Path(filename).name[:200], source, description))
    db.execute('UPDATE paper_documents SET current_version_id=? WHERE id=?', (vid, did))
    db.execute('UPDATE reader_annotations SET document_version_id=coalesce(document_version_id,?) WHERE paper_id=? AND file_version=?', (vid, pid, digest))
    db.commit()
    return {'version_id': vid, 'deduplicated': False}


def annotations(db, pid, row, origin='all'):
    result = []
    for a in annotation_repo.list_annotations(db, pid):
        if a['file_version'] != row['file_hash']:
            continue
        if origin == 'personal' and a['origin'] == 'ai':
            continue
        if origin == 'ai' and a['origin'] != 'ai':
            continue
        result.append(reader.annotation_view(a))
    return result


def guard_session(db, settings, state, sid):
    for link in db.execute('SELECT cp.*,p.pdf_path FROM conversation_papers cp JOIN papers p ON p.id=cp.paper_id WHERE conversation_id=?', (sid,)).fetchall():
        pid = link['paper_id']
        if pid in getattr(state, 'document_switches', set()):
            raise ServiceError(409, '论文正在切换版本，请稍后再试')
        if not link['pdf_path']:
            continue
        try:
            _, current = pages.pdf_file(settings, reader.paper(db, pid))
        except (ValueError, OSError):
            continue
        if link['file_version'] and link['file_version'] != current:
            raise ServiceError(409, '此会话使用旧 PDF 版本；请新建会话阅读当前版本，历史内容已保留')
        db.execute('UPDATE conversation_papers SET file_version=? WHERE conversation_id=? AND paper_id=?', (current, sid, pid))
    db.commit()


async def make_default(db, state, pid, vid, expected_version):
    ensure_paper(db, state.settings, pid)
    row = version(db, pid, vid)
    if row['role'] != 'main':
        raise ServiceError(400, '补充材料不能设为正文默认版本')
    paper = reader.paper(db, pid)
    if paper['default_version_id'] != expected_version:
        raise ServiceError(409, '默认版本已变化，请刷新后重试')
    if paper['default_version_id'] == vid and db.execute('SELECT 1 FROM chunks_meta WHERE paper_id=? LIMIT 1',(pid,)).fetchone():
        return {'version_id': vid, 'unchanged': True}
    if not hasattr(state, 'document_switches'):
        state.document_switches = set()
    if pid in state.document_switches:
        raise ServiceError(409, '论文正在切换版本')
    def active():
        return db.execute("SELECT 1 FROM agent_runs r JOIN conversation_papers cp ON cp.conversation_id=r.conversation_id WHERE cp.paper_id=? AND r.status IN ('queued','running') LIMIT 1", (pid,)).fetchone()
    if active():
        raise ServiceError(409, '论文有执行中任务，请先完成或取消')
    path = asset_path(state.settings, row['storage_key'])
    state.document_switches.add(pid)
    try:
        from ..ingest.pipeline import _parse_and_embed
        from ..rag.vector_store import ChunkPoint
        saved=db.execute('SELECT text,page,section FROM document_text_chunks WHERE version_id=? ORDER BY chunk_index',(vid,)).fetchall()
        if saved:
            from ..rag.chunker import Chunk
            chunks=[Chunk(text=c['text'],page=c['page'],section=c['section']) for c in saved]
            vectors=await asyncio.to_thread(state.embedder.embed,[c.text for c in chunks])
        else:chunks, vectors = await asyncio.to_thread(_parse_and_embed, path, state.embedder)
        if not chunks:
            raise ServiceError(400, '此 PDF 没有可索引文本，无法作为当前阅读版本')
        if active() or reader.paper(db, pid)['default_version_id'] != expected_version:
            raise ServiceError(409, '论文状态已变化，请刷新后重试')
        points = [ChunkPoint(paper_id=pid, chunk_index=i, text=c.text, page=c.page, section=c.section, vector=vectors[i]) for i, c in enumerate(chunks)]
        # The vector store compensates failure; SQLite changes stay in one transaction.
        with state.store.replacing_paper_chunks(pid, points), db:
            db.execute('DELETE FROM chunks_meta WHERE paper_id=?', (pid,))
            db.executemany('INSERT INTO chunks_meta(paper_id,chunk_idx,section,page,text) VALUES (?,?,?,?,?)', [(pid, i, c.section, c.page, c.text) for i, c in enumerate(chunks)])
            db.execute('DELETE FROM document_text_chunks WHERE version_id=?',(vid,))
            db.executemany('INSERT INTO document_text_chunks(version_id,chunk_index,text,page,section) VALUES (?,?,?,?,?)',[(vid,i,c.text,c.page,c.section) for i,c in enumerate(chunks)])
            db.execute('UPDATE papers SET pdf_path=?,default_version_id=? WHERE id=?', (str(path), vid, pid))
            db.execute('UPDATE paper_documents SET current_version_id=? WHERE id=?', (vid, row['document_id']))
        return {'version_id': vid, 'unchanged': False}
    finally:
        state.document_switches.discard(pid)
