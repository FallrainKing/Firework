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

TOOLS = [
    {"name": "library_search", "description": "Search the user's saved paper titles, abstracts and original text. Empty query lists papers. Read only. Page numbers from legacy chunks are unverified.", "inputSchema": SCHEMA},
    {"name": "arxiv_search", "description": "Search real arXiv papers by short English keywords. Returns titles, IDs, abstracts and source URLs. No PDF download or model call.", "inputSchema": SCHEMA},
    {"name":"paper_read", "description":"Read indexed original text for a paper associated with this task session. Returns bounded chunks and explicit coverage; not a full-paper or figure reading guarantee.", "inputSchema":{"type":"object","properties":{"paper_id":{"type":"integer","minimum":1},"start_chunk":{"type":"integer","minimum":0}},"required":["paper_id"],"additionalProperties":False}},

    {"name":"paper_page","description":"Read a physical PDF page with accurate page number and file version for a paper linked to this session.","inputSchema":{"type":"object","properties":{"paper_id":{"type":"integer","minimum":1},"page":{"type":"integer","minimum":1}},"required":["paper_id","page"],"additionalProperties":False}},
    {"name":"paper_search","description":"Search public academic metadata on arxiv or crossref. Returns real source records for a user to import.","inputSchema":{"type":"object","properties":{"query":{"type":"string","maxLength":200},"source":{"type":"string","enum":["arxiv","crossref"]}},"required":["query","source"],"additionalProperties":False}},
    {"name":"paper_import","description":"Execute only the import request ID bound to this Agent task. No arbitrary file path or network access.","inputSchema":{"type":"object","properties":{"request_id":{"type":"string","pattern":"^[a-f0-9]{32}$"}},"required":["request_id"],"additionalProperties":False}},
]

def paper_page(paper_id,page,db_path):
    from app.reader.pages import read_page
    from app.core.config import Settings
    if paper_id not in json.loads(os.environ.get('RESEARCH_PAPER_IDS','[]')):raise ValueError('Paper is not linked to this session')
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM papers WHERE id=?',(paper_id,)).fetchone()
        if row is None:raise ValueError('Paper not found')
        result=read_page(Settings(data_dir=Path(db_path).parent,qdrant_url='unused'),row,page)
    result['truncated']=len(result['text'])>14000;result['text']=result['text'][:14000]
    return result

def paper_search(query,source):
    if source=='arxiv':return arxiv_search(query)
    if source=='crossref':
        from app.paper_sources import crossref_search
        return asyncio.run(crossref_search(query))
    raise ValueError('Unknown academic source')

def paper_import(request_id):
    if request_id!=os.environ.get('RESEARCH_IMPORT_ID') or not request_id:raise ValueError('Import request not authorized for this task')
    token=Path(os.environ['RESEARCH_TOKEN_FILE']).read_text().strip()
    req=urllib.request.Request('http://127.0.0.1:8600/api/internal/imports/'+request_id+'/execute',data=b'{}',headers={'Content-Type':'application/json','X-Research-Tool-Token':token,'X-Research-Run-Id':os.environ['RESEARCH_RUN_ID']})
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
        rows = db.execute("SELECT id,title,authors,abstract,arxiv_id FROM papers WHERE title LIKE ? ESCAPE '\\' OR abstract LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 5", (pattern, pattern)).fetchall()
        papers = [dict(r) for r in rows]
        matched_count = db.execute("SELECT count(*) FROM papers WHERE title LIKE ? ESCAPE '\\' OR abstract LIKE ? ESCAPE '\\'", (pattern, pattern)).fetchone()[0]
        chunks = []
        if query:
            chunks = [dict(r) for r in db.execute("SELECT paper_id,section,page,substr(text,1,900) AS text FROM chunks_meta WHERE text LIKE ? ESCAPE '\\' LIMIT 3", (pattern,))]
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
                query = params.get('arguments', {}).get('query', '')
                if not isinstance(query, str) or len(query) > 200:
                    raise ValueError('query must be at most 200 characters')
                if name not in json.loads(os.environ.get('RESEARCH_ALLOWED_TOOLS', '[]')):
                    raise ValueError('tool not allowed by this skill')
                calls += 1
                if calls > int(os.environ.get('RESEARCH_MAX_TOOL_CALLS','2')):
                    raise ValueError('tool call limit reached; finish with existing results')
                started = time.monotonic()
                try:
                    arguments=params.get('arguments',{})
                    if name=='library_search':payload=library_search(query,os.environ['RESEARCH_DB_PATH'])
                    elif name=='arxiv_search':payload=arxiv_search(query)
                    elif name=='paper_read':payload=paper_read(arguments.get('paper_id'),arguments.get('start_chunk',0),os.environ['RESEARCH_DB_PATH'])
                    elif name=='paper_page':payload=paper_page(arguments.get('paper_id'),arguments.get('page'),os.environ['RESEARCH_DB_PATH'])
                    elif name=='paper_search':payload=paper_search(query,arguments.get('source'))
                    elif name=='paper_import':payload=paper_import(arguments.get('request_id'))
                    else:payload=None
                    if payload is None:
                        raise ValueError('unknown tool')
                    record = {'tool': name, 'query': query, 'ok': True, 'result': payload}
                    result = {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}], 'isError': False}
                except Exception as exc:
                    record = {'tool': name, 'query': query, 'ok': False, 'error': type(exc).__name__}
                    result = {'content': [{'type': 'text', 'text': 'Tool failed (' + type(exc).__name__ + '). Report the failure; do not invent results.'}], 'isError': True}
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
