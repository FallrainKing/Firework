"""Bounded public academic lookups. No model call or credential forwarding."""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse,urljoin,quote
import xml.etree.ElementTree as ET
import httpx

MAX_PDF_BYTES=30*1024*1024
DOI_RE=re.compile(r'^10\.\d{4,9}/\S+$',re.I)

def normalize_doi(value):
    value=re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',value.strip(),flags=re.I).strip()
    if not DOI_RE.fullmatch(value) or len(value)>500:raise ValueError('请输入有效 DOI 或 doi.org 链接')
    return value.lower()

async def public_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError('只支持公开 HTTPS PDF 链接，不接受登录凭据或自定义端口')
    try:
        addresses=await asyncio.to_thread(socket.getaddrinfo,parsed.hostname,443,type=socket.SOCK_STREAM)
    except OSError:raise ValueError('无法解析 PDF 链接域名')
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('禁止访问本机、内网或保留网络地址')
    return url

async def fetch_pdf(url):
    async with httpx.AsyncClient(timeout=httpx.Timeout(45),follow_redirects=False,trust_env=False) as client:
        for _ in range(4):
            await public_url(url)
            async with client.stream('GET',url,headers={'User-Agent':'research-assistant/0.3 (personal research)'}) as response:
                if response.status_code in (301,302,303,307,308):
                    url=urljoin(url,response.headers.get('location',''));continue
                response.raise_for_status()
                length=response.headers.get('content-length')
                if length and int(length)>MAX_PDF_BYTES:raise ValueError('PDF 文件超过 30MB 限额')
                data=bytearray()
                async for block in response.aiter_bytes():
                    data.extend(block)
                    if len(data)>MAX_PDF_BYTES:raise ValueError('PDF 文件超过 30MB 限额')
                if not bytes(data[:1024]).lstrip().startswith(b'%PDF-'):raise ValueError('链接未返回 PDF，可能是网页或需要登录的资源')
                return bytes(data)
    raise ValueError('PDF 链接重定向过多')

def strip_markup(text):
    return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',text or '')).strip()

def crossref_item(item):
    title=(item.get('title') or [''])[0]
    authors=[' '.join(filter(None,[a.get('given'),a.get('family')])) for a in item.get('author',[])][:100]
    affiliations=list(dict.fromkeys(a.get('name','').strip() for author in item.get('author',[]) for a in author.get('affiliation',[]) if a.get('name')))[:20]
    doi=item.get('DOI','').lower()
    return {'title':title,'authors':authors,'affiliations':affiliations,'abstract':strip_markup(item.get('abstract','')),'doi':doi,'url':'https://doi.org/'+doi if doi else item.get('URL'),'source':'crossref','arxiv_id':None}

async def doi_metadata(value):
    doi=normalize_doi(value)
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as c:
        r=await c.get('https://api.crossref.org/works/'+quote(doi,safe=''),headers={'User-Agent':'research-assistant/0.3 (personal research)'})
        r.raise_for_status()
    return crossref_item(r.json()['message'])

async def crossref_search(query):
    query=query.strip()
    if not query or len(query)>200:raise ValueError('请输入 1–200 字的检索词')
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get('https://api.crossref.org/works',params={'query.title':query,'rows':3,'select':'DOI,title,author,abstract,URL,published'},headers={'User-Agent':'research-assistant/0.3 (personal research)'})
        r.raise_for_status()
    return {'source':'crossref','query':query,'papers':[crossref_item(i) for i in r.json()['message']['items']]}

async def arxiv_metadata(value):
    from ..ingest.metadata import extract_arxiv_id,parse_arxiv_atom
    ident=extract_arxiv_id(value)
    last=None
    async with httpx.AsyncClient(timeout=8) as c:
        for host in ('export.arxiv.org','arxiv.org'):
            try:
                r=await c.get(f'https://{host}/api/query',params={'id_list':ident});r.raise_for_status()
                meta=parse_arxiv_atom(r.text,ident)
                return {'title':meta.title,'authors':meta.authors,'abstract':meta.abstract,'arxiv_id':ident,'categories':meta.categories,'url':f'https://arxiv.org/abs/{ident}','affiliations':[],'source':'arxiv'}
            except (httpx.HTTPError,ValueError) as e:last=e
        try:
            r=await c.get(f'https://arxiv.org/abs/{ident}');r.raise_for_status()
            return parse_arxiv_html(r.text,ident)
        except (httpx.HTTPError,ValueError) as e:last=e
    raise ValueError('arXiv 元数据暂时不可用') from last

# arXiv's public abstract page exposes its own citation metadata even when
# the Atom endpoint is unavailable. Parse only those first-party fields.
def parse_arxiv_html(text,ident):
    from html.parser import HTMLParser
    class Citation(HTMLParser):
        def __init__(self):super().__init__();self.fields={}
        def handle_starttag(self,tag,attrs):
            if tag!='meta':return
            a=dict(attrs);key=a.get('name') or a.get('property')
            if key and a.get('content'):self.fields.setdefault(key,[]).append(a['content'])
    parser=Citation();parser.feed(text);fields=parser.fields
    first=lambda key:(fields.get(key) or [''])[0]
    if first('citation_arxiv_id')!=ident or not first('citation_title'):raise ValueError('arXiv 页面缺少匹配的论文标识')
    return {'title':first('citation_title'),'authors':fields.get('citation_author',[]),'abstract':first('citation_abstract') or first('og:description'),'arxiv_id':ident,'categories':[],'url':f'https://arxiv.org/abs/{ident}','affiliations':[],'source':'arxiv','metadata_source':'arxiv_citation_meta'}
