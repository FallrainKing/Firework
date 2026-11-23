"""Version-bound annotations, evidence and positions, tested against actual PDFs."""
import pymupdf
from test_agent_mvp import client
from test_reader_imports import reading
from test_documents import documents,pdf,listing,upload
from app.research.router import router


def test_previewed_annotation_copy_is_idempotent_and_keeps_original(documents):
    c,s,sid,ctx=documents
    source=listing(c)['default_version_id']
    a=c.post('/api/reader/annotations',json={**ctx,'conversation_id':sid,'kind':'highlight'}).json()
    target=upload(c,pdf(ctx['quote'])).json()['version_id']
    body={'source_version_id':source,'target_version_id':target,'annotation_ids':[a['id']]}
    path='/api/library/papers/1/annotation-migration-preview'
    r=c.post(path,json=body);assert r.status_code==200,r.text
    plan=r.json();assert plan['items'][0]['eligible']
    confirm={**body,'confirmation_hash':plan['confirmation_hash']}
    for _ in range(2):
        r=c.post('/api/library/papers/1/annotation-migrations',json=confirm);assert r.status_code==200,r.text
    assert len(r.json()['copied_ids'])==1
    old=c.get(f'/api/library/papers/1/document-versions/{source}/annotations').json()['annotations']
    new=c.get(f'/api/library/papers/1/document-versions/{target}/annotations').json()['annotations']
    assert len(old)==len(new)==1 and old[0]['id']==a['id'] and new[0]['id']!=a['id']
    assert all(len(rect)==4 for rect in new[0]['rects'])
    c.patch('/api/reader/annotations/'+a['id'],json={'content':'Changed'})
    assert c.post('/api/library/papers/1/annotation-migrations',json=confirm).status_code==409


def test_ambiguous_quote_does_not_migrate(documents):
    c,s,sid,ctx=documents;source=listing(c)['default_version_id']
    a=c.post('/api/reader/annotations',json={**ctx,'kind':'highlight'}).json()
    with pymupdf.open() as document:
        page=document.new_page(width=600,height=600)
        page.insert_text((40,70),ctx['quote']);page.insert_text((40,100),ctx['quote'])
        repeated=document.tobytes()
    target=upload(c,repeated).json()['version_id']
    r=c.post('/api/library/papers/1/annotation-migration-preview',json={'source_version_id':source,'target_version_id':target,'annotation_ids':[a['id']]})
    assert r.status_code==200,r.text
    assert not r.json()['items'][0]['eligible']


def test_old_pdf_citation_remains_after_default_switch(documents):
    c,s,sid,ctx=documents;c.app.include_router(router)
    source=listing(c)['default_version_id']
    evidence={'paper_id':1,'document_version_id':source,'file_version':ctx['file_version'],'page':1,'quote':ctx['quote']}
    r=c.post('/api/research/artifacts',json={'title':'Evidence','markdown':'Finding','paper_ids':[1],'evidence':[evidence],'status':'complete'})
    assert r.status_code==201,r.text
    a=r.json();assert a['evidence'][0]['verification']=='quote_verified'
    target=upload(c,pdf('Different text')).json()['version_id']
    r=c.post(f'/api/library/papers/1/document-versions/{target}/default',json={'confirmed':True,'expected_version_id':source});assert r.status_code==200,r.text
    old=c.get('/api/research/artifacts/'+a['id']).json()['evidence'][0]
    assert old['document_version_id']==source and old['file_version']==ctx['file_version']
    assert c.get(f'/api/library/papers/1/document-versions/{source}/file').status_code==200
    bad={**evidence,'quote':'Invented quote'}
    assert c.post('/api/research/artifacts',json={'title':'Bad','markdown':'Bad','paper_ids':[1],'evidence':[bad]}).status_code==409
