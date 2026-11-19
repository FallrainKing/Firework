"""Version-bound PDF blocks; coordinates are derived from real glyphs, never LLMs."""
import hashlib,json,unicodedata
import pymupdf
from .. import pages

MAX_CHARS=30000

def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text) if not c.isspace() and c!='\u00ad').replace('−','-').replace('–','-')


def extract(settings,row,task_id,selected):
    path,version=pages.pdf_file(settings,row)
    blocks=[];remaining=MAX_CHARS;provided=[];truncated=False
    with pymupdf.open(path) as doc:
        for number in selected:
            if number<1 or number>len(doc):raise ValueError('材料页码超出范围')
            page=doc[number-1];provided.append(number)
            for bindex,block in enumerate(page.get_text('rawdict',sort=True)['blocks']):
                if block.get('type')!=0:continue
                text='';mapping=[];norm=''
                for lindex,line in enumerate(block.get('lines',[])):
                    for span in line['spans']:
                        for char in span.get('chars',[]):
                            raw=char['c']
                            if len(text)>=min(remaining,4000):truncated=True;break
                            text+=raw
                            r=pymupdf.Rect(char['bbox'])*page.rotation_matrix
                            rect=[max(0,min(1,r.x0/page.rect.width)),max(0,min(1,r.y0/page.rect.height)),max(0,min(1,r.x1/page.rect.width)),max(0,min(1,r.y1/page.rect.height))]
                            for c in normalized(raw):norm+=c;mapping.append([lindex,*rect])
                    text+='\n'
                text=text.strip()
                if not text:continue
                if remaining<=0:truncated=True;break
                remaining-=len(text)
                ident=f'p{number}-b{bindex}-'+hashlib.sha256(text.encode()).hexdigest()[:10]
                blocks.append({'id':ident,'material_id':f'page-{number}','page':number,'text':text,'data':{'norm':norm,'mapping':mapping,'rotation':page.rotation}})
            if remaining<=0:break
    return {'file_version':version,'blocks':blocks,'provided_pages':provided,'truncated':truncated}


def locate(block,anchor):
    if anchor.type!='text':return {'page':block['page'],'quote':'','rects':[],'status':'page_only','block_id':block['id']}
    data=json.loads(block['data_json']);needle=normalized(anchor.quote);text=data['norm']
    hits=[];start=0
    while needle:
        index=text.find(needle,start)
        if index<0:break
        before=normalized(anchor.prefix);after=normalized(anchor.suffix)
        if (not before or text[:index].endswith(before)) and (not after or text[index+len(needle):].startswith(after)):hits.append(index)
        start=index+1
    if len(hits)!=1:return {'page':block['page'],'quote':anchor.quote,'rects':[],'status':'ambiguous' if hits else 'unlocated','block_id':block['id']}
    groups={}
    for line,x0,y0,x1,y1 in data['mapping'][hits[0]:hits[0]+len(needle)]:
        r=groups.setdefault(line,[x0,y0,x1,y1]);r[:]=[min(r[0],x0),min(r[1],y0),max(r[2],x1),max(r[3],y1)]
    rects=[[x0,y0,x1-x0,y1-y0] for x0,y0,x1,y1 in groups.values() if x1>x0 and y1>y0]
    return {'page':block['page'],'quote':anchor.quote,'rects':rects[:100],'status':'verified' if rects else 'page_only','block_id':block['id']}
