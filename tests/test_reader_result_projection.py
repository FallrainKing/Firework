"""Legacy guide-cache isolation without deleting papers, conversations or evidence."""
import json
from app.research import service
from test_research_platform import research,artifact
from test_documents import pdf,listing,upload
from test_agent_mvp import client
from test_reader_imports import reading


def test_legacy_translation_and_guide_receipts_never_become_reader_summaries(research):
    c,s,sid,ctx=research;db=c.app.state.db
    # Old code marked every response as reading, including translations and guide receipts.
    for purpose in ['translate','explain','guide','skill-validation']:
        ident=('old-'+purpose)
        db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,answer,status,purpose) VALUES (?,?,?,'paper_read',?,'old cached result','succeeded',?)",(ident,ident,sid,purpose,purpose))
        a=artifact(c,title='old '+purpose,kind='reading')
        db.execute('UPDATE research_artifacts SET source_run_id=?,source_key=? WHERE id=?',(ident,'run:'+ident,a['id']))
    db.commit()
    assert c.get('/api/research/artifacts?paper_id=1').json()['artifacts']
    r=c.get('/api/research/artifacts',params={'paper_id':1,'reader_file_version':ctx['file_version']})
    assert r.status_code==200,r.text
    assert r.json()['artifacts']==r.json()['unverified_artifacts']==[]
    assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]==4


def test_current_version_results_and_unknown_history_are_separate(research):
    c,s,sid,ctx=research;db=c.app.state.db;vid=listing(c)['default_version_id']
    evidence={'paper_id':1,'document_version_id':vid,'file_version':ctx['file_version'],'page':1,'quote':ctx['quote']}
    current=artifact(c,title='Current summary',kind='guide',evidence=[evidence])
    unknown=artifact(c,title='Old unversioned summary',kind='reading')
    artifact(c,title='Unfinished',kind='reading',status='draft')
    new=upload(c,pdf('Other source text')).json()['version_id']
    version=c.get('/api/reader/papers/1',params={'version_id':new}).json()
    other=artifact(c,title='Other version',kind='reading',evidence=[{'paper_id':1,'document_version_id':new,'file_version':version['file_version'],'page':1,'quote':'Other source text'}])
    data=c.get('/api/research/artifacts',params={'paper_id':1,'reader_file_version':ctx['file_version']}).json()
    assert [a['id'] for a in data['artifacts']]==[current['id']]
    assert [a['id'] for a in data['unverified_artifacts']]==[unknown['id']]
    assert data['older_versions']==1
    assert c.get('/api/research/artifacts',params={'paper_id':2,'reader_file_version':ctx['file_version']}).status_code==404
    assert c.get('/api/research/artifacts',params={'reader_file_version':ctx['file_version']}).status_code==422
    assert c.get('/api/research/artifacts/'+other['id']).status_code==200
