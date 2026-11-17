"""Deterministic PDF previews and source-labelled affiliation candidates."""
from pathlib import Path
import re
import pymupdf

_INSTITUTION=re.compile(r'University|Universit[äé]|Institute|Laborator|College|School of|Google|DeepMind|Microsoft|Berkeley|Stanford|MIT\b|Physical Intelligence|\bFAIR\b|Meta AI|大学|研究院|研究所|实验室',re.I)

def safe_pdf(settings,pdf_path):
    if not pdf_path:raise ValueError('PDF unavailable')
    path=Path(pdf_path).resolve();root=(settings.data_dir/'papers').resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('PDF unavailable')
    return path

def preview_path(settings,pdf_path):
    source=safe_pdf(settings,pdf_path)
    stat=source.stat();cache=settings.data_dir/'previews';cache.mkdir(parents=True,exist_ok=True)
    target=cache/f'{source.stem}-{stat.st_mtime_ns}-{stat.st_size}.png'
    if not target.exists():
        with pymupdf.open(source) as doc:
            if len(doc)==0:raise ValueError('Empty PDF')
            page=doc[0];scale=min(520/page.rect.width,720/page.rect.height)
            pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
            # Atomic replace prevents browsers reading a partially written PNG.
            temp=target.with_suffix('.tmp.png');pix.save(temp);temp.replace(target)
    return target

def affiliation_candidates(settings,pdf_path):
    source=safe_pdf(settings,pdf_path)
    with pymupdf.open(source) as doc:
        text=doc[0].get_text('text') if len(doc) else ''
    values=[]
    for line in text.splitlines():
        line=' '.join(line.split())
        if any(x in line.lower() for x in ('control suite','simulated tasks','all rights reserved','©','copyright')):
            continue
        line=line.split('. Authors listed',1)[0]
        line=re.split(r',?\s*[†‡]Work done',line)[0]
        for part in re.split(r',\s*(?=\d{1,2}\s*[A-Z])',line):
            part=re.sub(r'^[\d,*†‡\s]+','',part).rstrip(' .,')
            if 2<len(part)<160 and len(part.split())<=14 and _INSTITUTION.search(part) and '@' not in part and not part.startswith(('http','www','Work done')):
                if part not in values:values.append(part)
            if len(values)>=8:return values
    return values
