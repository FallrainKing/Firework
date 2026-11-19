"""Bounded first-party discovery. The Agent selects queries; adapters fetch facts."""
import asyncio
import time
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET
import httpx

_locks={}
_last={}

async def search(source,query,start,end,limit,offset=0):
    lock=_locks.setdefault(source,asyncio.Lock())
    async with lock:
        delay={'arxiv':3,'github':6,'crossref':1}.get(source,1)-(time.monotonic()-_last.get(source,0))
        if delay>0:await asyncio.sleep(delay)
        _last[source]=time.monotonic()
        return await _search(source,query,start,end,limit,offset)

async def _search(source,query,start,end,limit,offset=0):
    if not query.strip() or len(query)>200:raise ValueError('检索词需 1–200 字')
    async with httpx.AsyncClient(timeout=25,follow_redirects=False,trust_env=False,headers={'User-Agent':'research-assistant-frontier/1.0','Accept':'application/json'}) as c:
        if source=='github':
            # Repository search is explicitly bounded; activity is not a code-quality verdict.
            q=f'{query} pushed:{start[:10]}..{end[:10]}'
            r=await c.get('https://api.github.com/search/repositories',params={'q':q,'sort':'updated','order':'desc','per_page':limit,'page':offset//limit+1})
            r.raise_for_status();data=r.json()
            records=[{'kind':'project','repo_id':x['id'],'title':x['full_name'],'url':x['html_url'],'owner':x['owner']['login'],'description':x.get('description') or '', 'license':(x.get('license') or {}).get('spdx_id'),'archived':x.get('archived',False),'activity_at':x.get('pushed_at'),'stars':x.get('stargazers_count'), 'evidence_level':'metadata'} for x in data.get('items',[])]
            # Check bounded release metadata; never execute or clone repository code.
            for m in records[:5]:
                try:
                    rel=await c.get('https://api.github.com/repos/'+quote(m['title'],safe='/')+'/releases/latest',timeout=5)
                    if rel.status_code==404:m.update(release=None,release_checked=True)
                    else:
                        rel.raise_for_status();v=rel.json();m.update(release={'id':v['id'],'tag':v['tag_name'],'published_at':v.get('published_at'),'url':v['html_url']},release_checked=True)
                except (httpx.HTTPError,KeyError,ValueError):m['release_checked']=False
            total=data.get('total_count',len(records));truncated=total>offset+len(records) or data.get('incomplete_results',False)
        elif source=='crossref':
            r=await c.get('https://api.crossref.org/works',params={'query':query,'rows':limit,'offset':offset,'filter':f'from-pub-date:{start[:10]},until-pub-date:{end[:10]}','sort':'published','order':'desc'})
            r.raise_for_status();data=r.json()['message']
            from ..imports.sources import crossref_item
            records=[dict(crossref_item(x),kind='paper',evidence_level='abstract' if x.get('abstract') else 'metadata') for x in data.get('items',[])]
            total=data.get('total-results',len(records));truncated=total>offset+len(records)
        elif source=='arxiv':
            terms=query.replace('\n',' ')
            r=await c.get('https://export.arxiv.org/api/query',params={'search_query':terms,'sortBy':'lastUpdatedDate','sortOrder':'descending','max_results':limit,'start':offset})
            r.raise_for_status();root=ET.fromstring(r.text);ns='{http://www.w3.org/2005/Atom}'
            records=[]
            entries=root.findall(ns+'entry')
            for x in entries:
                updated=x.findtext(ns+'updated') or x.findtext(ns+'published') or ''
                if updated[:10]<start[:10] or updated[:10]>end[:10]:continue
                url=(x.findtext(ns+'id') or '').replace('http://','https://')
                if not url.startswith('https://arxiv.org/abs/'):continue
                records.append({'kind':'paper','title':' '.join((x.findtext(ns+'title') or '').split()),'arxiv_id':url.split('/abs/')[1],'url':url,'abstract':' '.join((x.findtext(ns+'summary') or '').split())[:6000],'authors':[a.findtext(ns+'name') for a in x.findall(ns+'author')],'published':x.findtext(ns+'published'),'updated':updated,'evidence_level':'abstract'})
            total=int(root.findtext('{http://a9.com/-/spec/opensearch/1.1/}totalResults') or len(entries));truncated=bool(entries) and total>offset+len(entries) and (entries[-1].findtext(ns+'updated') or '')[:10]>=start[:10]
        else:raise ValueError('不支持的数据源')
    return {'records':records,'total':total,'truncated':bool(truncated),'window_start':start,'window_end':end,'offset':offset,'next_offset':offset+(len(entries) if source=='arxiv' else len(records)) if truncated and (entries if source=='arxiv' else records) else None}
