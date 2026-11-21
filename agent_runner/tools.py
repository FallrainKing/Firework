"""Scoped stdio MCP server. stdout is JSON-RPC only."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

SCHEMA = {"type": "object", "properties": {"query": {"type": "string", "maxLength": 200}}, "required": ["query"], "additionalProperties": False}
_last_arxiv_request = 0.0

from app.reader.guides.schemas import GuideResult

TOOLS = [
    {"name":"reader_guide_context","description":"Read this explicitly triggered guide task, exact PDF version, outline and allowed scope.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}},
    {"name":"reader_guide_material","description":"Read bounded real PDF text blocks. Only returned block_id and material_id can be cited. No figure or code understanding.","inputSchema":{"type":"object","properties":{"pages":{"type":"array","items":{"type":"integer","minimum":1},"minItems":1,"maxItems":6}},"required":["pages"],"additionalProperties":False}},
    {"name":"reader_guide_submit","description":"Stage a paper-guide/v1 structured result from actual blocks. Never output rectangles or invented evidence; unavailable topics go into unknown_fields.","inputSchema":GuideResult.model_json_schema()},
    {"name":"frontier_context","description":"Read the current authorized tracker configuration, source windows and limits.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}},
    {"name":"frontier_search","description":"Search a configured academic/project source. Persists actual evidence and returns global dedup labels; never approves or imports.","inputSchema":{"type":"object","properties":{"source":{"type":"string","enum":["arxiv","crossref","github"]},"query":{"type":"string","maxLength":200}},"required":["source","query"],"additionalProperties":False}},
    {"name":"frontier_report","description":"Save a Chinese evidence-grounded frontier digest after searches. Reference evidence IDs returned by frontier_search. Include failures and truncated coverage.","inputSchema":{"type":"object","properties":{"markdown":{"type":"string","maxLength":20000},"citations":{"type":"array","items":{"type":"string"}},"reasons":{"type":"object","additionalProperties":{"type":"string"}}},"required":["markdown","citations"],"additionalProperties":False}},
    {"name": "library_search", "description": "Search the user's saved paper titles, abstracts and original text. Empty query lists papers. Read only. Page numbers from legacy chunks are unverified.", "inputSchema": SCHEMA},
    {"name": "arxiv_search", "description": "Search real arXiv papers by short English keywords. Returns titles, IDs, abstracts and source URLs. No PDF download or model call.", "inputSchema": SCHEMA},
    {"name":"paper_read", "description":"Read indexed original text for a paper associated with this task session. Returns bounded chunks and explicit coverage; not a full-paper or figure reading guarantee.", "inputSchema":{"type":"object","properties":{"paper_id":{"type":"integer","minimum":1},"start_chunk":{"type":"integer","minimum":0}},"required":["paper_id"],"additionalProperties":False}},

    {"name":"paper_page","description":"Read a physical PDF page with accurate page number and file version for a paper linked to this session.","inputSchema":{"type":"object","properties":{"paper_id":{"type":"integer","minimum":1},"page":{"type":"integer","minimum":1}},"required":["paper_id","page"],"additionalProperties":False}},
    {"name":"paper_search","description":"Search public academic metadata on arxiv or crossref. Returns real source records for a user to import.","inputSchema":{"type":"object","properties":{"query":{"type":"string","maxLength":200},"source":{"type":"string","enum":["arxiv","crossref"]}},"required":["query","source"],"additionalProperties":False}},
    {"name":"paper_import","description":"Execute only the import request ID bound to this Agent task. No arbitrary file path or network access.","inputSchema":{"type":"object","properties":{"request_id":{"type":"string","pattern":"^[a-f0-9]{32}$"}},"required":["request_id"],"additionalProperties":False}},
    {"name":"skill_resource","description":"Read a text resource from the exact skill version bound to this run. Relative paths only; other versions and host files are inaccessible.","inputSchema":{"type":"object","properties":{"path":{"type":"string","minLength":1,"maxLength":260,"pattern":"^(?!/)(?!\\\\)[^\\\\]+$"}},"required":["path"],"additionalProperties":False}},
]

_SKILL_RESOURCE_SUFFIXES = {'.md', '.txt', '.json', '.yaml', '.yml'}
_SKILL_RESOURCE_PER_CALL_CHARS = 20_000
_SKILL_RESOURCE_TOTAL_CHARS = 200_000


def paper_page(paper_id,page,db_path):
    from app.reader.pages import read_page
    from app.core.config import Settings
    if paper_id not in json.loads(os.environ.get('RESEARCH_PAPER_IDS','[]')):raise ValueError('Paper is not linked to this session')
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
        if row is None:raise ValueError('Paper not found')
        result=read_page(Settings(data_dir=Path(db_path).parent,qdrant_url='unused',workspace_key=os.environ.get('RESEARCH_WORKSPACE','legacy')),row,page)
    result['truncated']=len(result['text'])>14000;result['text']=result['text'][:14000]
    return result

def paper_search(query,source):
    if source=='arxiv':return arxiv_search(query)
    if source=='crossref':
        from app.imports.sources import crossref_search
        return asyncio.run(crossref_search(query))
    raise ValueError('Unknown academic source')

def internal_call(path,arguments):
    token=Path(os.environ['RESEARCH_TOKEN_FILE']).read_text().strip()
    req=urllib.request.Request('http://127.0.0.1:8600/api/internal/'+path,data=json.dumps(arguments,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','X-Research-Tool-Token':token,'X-Research-Run-Id':os.environ['RESEARCH_RUN_ID'],'X-Research-Workspace':os.environ.get('RESEARCH_WORKSPACE','legacy')})
    try:
        with urllib.request.urlopen(req,timeout=45) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        try:detail=json.loads(exc.read(2500)).get('detail','请求被拒绝')
        except (ValueError,AttributeError):detail='请求被拒绝'
        raise ValueError(str(detail)[:1800]) from None

def frontier_call(action,arguments):
    token=Path(os.environ['RESEARCH_TOKEN_FILE']).read_text().strip()
    req=urllib.request.Request('http://127.0.0.1:8600/api/internal/frontier/'+action,data=json.dumps(arguments,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','X-Research-Tool-Token':token,'X-Research-Run-Id':os.environ['RESEARCH_RUN_ID'],'X-Research-Workspace':os.environ.get('RESEARCH_WORKSPACE','legacy')})
    with urllib.request.urlopen(req,timeout=45) as response:return json.load(response)

def paper_import(request_id):
    if request_id!=os.environ.get('RESEARCH_IMPORT_ID') or not request_id:raise ValueError('Import request not authorized for this task')
    token=Path(os.environ['RESEARCH_TOKEN_FILE']).read_text().strip()
    req=urllib.request.Request('http://127.0.0.1:8600/api/internal/imports/'+request_id+'/execute',data=b'{}',headers={'Content-Type':'application/json','X-Research-Tool-Token':token,'X-Research-Run-Id':os.environ['RESEARCH_RUN_ID'],'X-Research-Workspace':os.environ.get('RESEARCH_WORKSPACE','legacy')})
    with urllib.request.urlopen(req,timeout=100) as response:return json.load(response)

def paper_read(paper_id: int, start_chunk: int, db_path: str) -> dict:
    allowed=json.loads(os.environ.get('RESEARCH_PAPER_IDS','[]'))
    if paper_id not in allowed:
        raise ValueError('Paper is not associated with this task session')
    if not isinstance(start_chunk,int) or start_chunk<0:
        raise ValueError('Invalid chunk offset')
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT id,title,abstract,authors FROM papers WHERE id=?',(paper_id,)).fetchone()
        if row is None:raise ValueError('Paper not found')
        total=db.execute('SELECT count(*) FROM chunks_meta WHERE paper_id=?',(paper_id,)).fetchone()[0]
        chunks=[dict(r) for r in db.execute('SELECT chunk_idx,section,page,text FROM chunks_meta WHERE paper_id=? AND chunk_idx>=? ORDER BY chunk_idx LIMIT 8',(paper_id,start_chunk))]
    return {'paper':dict(row),'chunks':chunks,'total_chunks':total,'next_chunk_idx':chunks[-1]['chunk_idx']+1 if chunks else None,'has_more':bool(chunks and chunks[-1]['chunk_idx']+1<total),'coverage':{'scope':'indexed_text_only','returned_chunks':len(chunks),'total_chunks':total,'figures_read':False},'warning':'This is bounded indexed text, not the complete paper. Legacy page numbers are unverified.'}

def library_search(query: str, db_path: str) -> dict:
    # Literal substring search, not an SQL wildcard language.
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    with sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT id,title,authors,abstract,arxiv_id FROM papers WHERE deleted_at IS NULL AND (title LIKE ? ESCAPE '\\' OR abstract LIKE ? ESCAPE '\\') ORDER BY id DESC LIMIT 5", (pattern, pattern)).fetchall()
        papers = [dict(r) for r in rows]
        matched_count = db.execute("SELECT count(*) FROM papers WHERE deleted_at IS NULL AND (title LIKE ? ESCAPE '\\' OR abstract LIKE ? ESCAPE '\\')", (pattern, pattern)).fetchone()[0]
        chunks = []
        if query:
            chunks = [dict(r) for r in db.execute("SELECT cm.paper_id,cm.section,cm.page,substr(cm.text,1,900) AS text FROM chunks_meta cm JOIN papers p ON p.id=cm.paper_id WHERE p.deleted_at IS NULL AND cm.text LIKE ? ESCAPE '\\' LIMIT 3", (pattern,))]
    for p in papers:
        p['abstract'] = (p['abstract'] or '')[:1200]
        p['url'] = 'https://arxiv.org/abs/' + p['arxiv_id'] if p['arxiv_id'] else None
    return {'source': 'saved_library', 'papers': papers, 'matched_count': matched_count, 'returned_count': len(papers), 'excerpts': chunks, 'warning': 'Legacy chunk page numbers are unverified; do not call them exact citations.'}

def arxiv_search(query: str) -> dict:
    global _last_arxiv_request
    if not query.strip():
        raise ValueError('arXiv query must not be empty')
    # Omit redundant defaults: some upstream caches treat query variants
    # differently. Two results are enough for this low-usage connectivity MVP.
    params = urllib.parse.urlencode({'search_query': 'all:' + query, 'max_results': 2})
    raw = None
    last_error = None
    for host in ('export.arxiv.org', 'arxiv.org'):
        req = urllib.request.Request('https://' + host + '/api/query?' + params, headers={'User-Agent': 'research-assistant/0.2 (personal research tool)'})
        delay = 3.0 - (time.monotonic() - _last_arxiv_request)
        if delay > 0:
            time.sleep(delay)
        _last_arxiv_request = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = response.read(512 * 1024 + 1)
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
    if raw is None:
        raise last_error
    if len(raw) > 512 * 1024:
        raise ValueError('arXiv response exceeds size limit')
    root = ET.fromstring(raw)
    atom = '{http://www.w3.org/2005/Atom}'
    papers = []
    for item in root.findall(atom + 'entry'):
        url = (item.findtext(atom + 'id') or '').strip().replace('http://', 'https://', 1)
        if not url.startswith('https://arxiv.org/abs/'):
            raise ValueError('arXiv returned an invalid entry')
        papers.append({'title': ' '.join((item.findtext(atom + 'title') or '').split()), 'url': url, 'arxiv_id': url.split('/abs/', 1)[1], 'abstract': ' '.join((item.findtext(atom + 'summary') or '').split())[:1200], 'published': item.findtext(atom + 'published'), 'authors':[(a.findtext(atom+'name') or '').strip() for a in item.findall(atom+'author')]})
    return {'source': 'arxiv', 'query': query, 'papers': papers, 'result_limit': 2}

def skill_resource(path: str) -> dict:
    root = Path(os.environ['RESEARCH_SKILL_ROOT']).resolve()
    rel = Path(path)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Only relative paths inside the skill package are allowed')
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError('Path escapes the skill package') from None
    if target.is_symlink() or target.suffix.lower() not in _SKILL_RESOURCE_SUFFIXES:
        raise ValueError('Resource type is not allowed')
    if not target.is_file():
        raise ValueError('Resource not found')
    if target.stat().st_size > 1024 * 1024:
        raise ValueError('Resource exceeds the 1MB limit')
    used = int(os.environ.get('RESEARCH_SKILL_CHARS_USED', '0'))
    remaining = _SKILL_RESOURCE_TOTAL_CHARS - used
    if remaining <= 0:
        raise ValueError('Skill resource read budget exhausted')
    text = target.read_text(encoding='utf-8')[:min(_SKILL_RESOURCE_PER_CALL_CHARS, remaining)]
    os.environ['RESEARCH_SKILL_CHARS_USED'] = str(used + len(text))
    return {
        'path': rel.as_posix(),
        'skill_hash': os.environ.get('RESEARCH_SKILL_HASH', ''),
        'content': text,
        'truncated': len(text) == _SKILL_RESOURCE_PER_CALL_CHARS,
        'remaining_chars': _SKILL_RESOURCE_TOTAL_CHARS - used - len(text),
    }


def serve() -> None:
    calls = 0
    for line in sys.stdin:
        try:
            req = json.loads(line)
            if 'id' not in req:
                continue
            method = req.get('method')
            if method == 'initialize':
                result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'research-scoped', 'version': '0.3.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                allowed=json.loads(os.environ.get('RESEARCH_ALLOWED_TOOLS','[]'))
                result = {'tools': [t for t in TOOLS if t['name'] in allowed]}
            elif method == 'tools/call':
                params = req.get('params', {})
                name = params.get('name')
                arguments = params.get('arguments', {})
                query = arguments.get('query', '')
                if name in ('library_search', 'arxiv_search') and (not isinstance(query, str) or len(query) > 200):
                    raise ValueError('query must be at most 200 characters')
                if name == 'paper_search' and not isinstance(arguments.get('query'), str):
                    raise ValueError('query is required')
                if name not in json.loads(os.environ.get('RESEARCH_ALLOWED_TOOLS', '[]')):
                    raise ValueError('tool not allowed by this skill')
                calls += 1
                if calls > int(os.environ.get('RESEARCH_MAX_TOOL_CALLS','2')):
                    raise ValueError('tool call limit reached; finish with existing results')
                started = time.monotonic()
                try:
                    if name=='library_search':payload=library_search(query,os.environ['RESEARCH_DB_PATH'])
                    elif name=='arxiv_search':payload=arxiv_search(query)
                    elif name=='paper_read':payload=paper_read(arguments.get('paper_id'),arguments.get('start_chunk',0),os.environ['RESEARCH_DB_PATH'])
                    elif name=='paper_page':payload=paper_page(arguments.get('paper_id'),arguments.get('page'),os.environ['RESEARCH_DB_PATH'])
                    elif name=='paper_search':payload=paper_search(query,arguments.get('source'))
                    elif name=='paper_import':payload=paper_import(arguments.get('request_id'))
                    elif name in ('reader_guide_context','reader_guide_material','reader_guide_submit'):payload=internal_call('reader-guide/'+name.removeprefix('reader_guide_'),arguments)
                    elif name in ('frontier_context','frontier_search','frontier_report'):payload=frontier_call(name.removeprefix('frontier_'),arguments)
                    elif name=='skill_resource':payload=skill_resource(arguments.get('path',''))
                    else:payload=None
                    if payload is None:
                        raise ValueError('unknown tool')
                    record = {'tool': name, 'query': query, 'ok': True, 'result': payload}
                    result = {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}], 'isError': False}
                except Exception as exc:
                    record = {'tool': name, 'query': query, 'ok': False, 'error': type(exc).__name__}
                    result = {'content': [{'type': 'text', 'text': ('导读工具失败：'+str(exc)[:1800]) if name.startswith('reader_guide_') else 'Tool failed (' + type(exc).__name__ + '). Report the failure; do not invent results.'}], 'isError': True}
                record['duration_ms'] = round((time.monotonic() - started) * 1000)
                log = os.environ.get('RESEARCH_TOOL_LOG')
                if log:
                    with open(log, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
                continue
            out = {'jsonrpc': '2.0', 'id': req['id'], 'result': result}
        except Exception as exc:
            out = {'jsonrpc': '2.0', 'id': req.get('id') if isinstance(locals().get('req'), dict) else None, 'error': {'code': -32602, 'message': str(exc)[:200]}}
        print(json.dumps(out, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    serve()
