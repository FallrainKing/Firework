"""Deterministic identities, independent of model opinions."""
import hashlib
import json
import re
from urllib.parse import urlparse,unquote


def identifiers(m):
    if m.get('kind')=='project':
        path=urlparse(m.get('url','')).path.strip('/').removesuffix('.git').lower()
        if urlparse(m.get('url','')).hostname!='github.com' or not re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+',path):raise ValueError('无效项目链接')
        keys=['repo:'+path]
        if m.get('repo_id'):keys.insert(0,'github:'+str(m['repo_id']))
        return keys
    keys=[]
    doi=re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',m.get('doi') or '',flags=re.I).strip().lower()
    if doi:
        if not re.fullmatch(r'10\.\d{4,9}/\S+',doi):raise ValueError('无效 DOI')
        keys.append('doi:'+doi)
    arxiv=m.get('arxiv_id') or ''
    if arxiv:
        arxiv=re.sub(r'v\d+$','',arxiv)
        if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})',arxiv):raise ValueError('无效 arXiv 标识')
        keys.append('arxiv:'+arxiv)
    if not keys:raise ValueError('缺少可核验的论文标识')
    return keys


def fingerprint(m):
    # Retrieval timestamps, ranks and stars cannot create fake novelty.
    fields=('title','abstract','authors','affiliations','arxiv_id','doi') if m.get('kind')!='project' else ('title','description','license','release','archived')
    return hashlib.sha256(json.dumps({k:m.get(k) for k in fields},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def find_paper(db,m):
    keys=identifiers(m)
    for p in db.execute('SELECT id,doi,arxiv_id,source_url FROM papers'):
        try:
            other=identifiers(dict(p))
        except ValueError:other=[]
        if set(keys)&set(other):return p['id']
    return None


def similar_papers(db,m):
    def norm(s):return re.sub(r'[^\w]','',s.casefold())
    title=norm(m.get('title',''))
    return [p['id'] for p in db.execute('SELECT id,title FROM papers') if title and norm(p['title'] or '')==title][:5]
