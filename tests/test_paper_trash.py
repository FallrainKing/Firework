"""Reversible removal, preserved evidence, busy guards and account boundaries."""
import sqlite3
import json
from test_agent_mvp import client
from test_task_sessions import paper
from test_auth_accounts import secured, user, paper as private_paper


def test_trash_restore_preserves_identity_files_categories_and_history(client, tmp_path):
    c, settings = client
    path = tmp_path / 'original.pdf'
    path.write_bytes(b'%PDF-preserved-test-material')
    pid = paper(settings, 'Keep evidence', path)
    collection = c.post('/api/library/collections', json={'name': 'Keep category'}).json()
    c.patch(f'/api/library/papers/{pid}', json={'metadata_version': 1, 'collection_ids': [collection['id']]})
    sid = c.post('/api/sessions', json={'template_id': 'read', 'paper_ids': [pid]}).json()['session']['id']
    with sqlite3.connect(settings.db_path) as db:
        db.execute("INSERT INTO reader_annotations(id,paper_id,conversation_id,file_version,page,kind,content) VALUES ('note',?,?,'version',1,'note','Keep annotation')", (pid, sid))
        db.execute("INSERT INTO chunks_meta(paper_id,chunk_idx,text) VALUES (?,0,'Keep evidence excerpt')", (pid,))
        db.execute("INSERT INTO reader_states(conversation_id,paper_id) VALUES (?,?)", (sid, pid))
        db.execute('INSERT INTO workspace_states(id,state_json) VALUES (?,?)', ('a'*32, json.dumps({'tabs': [{'paper_id': pid, 'session_id': sid}], 'active_paper_id': pid, 'view': 'read'})))
    assert c.delete(f'/api/library/papers/{pid}').status_code == 200
    assert c.delete(f'/api/library/papers/{pid}').status_code == 200  # idempotent
    assert c.get('/api/library/papers').json()['total'] == 0
    trash = c.get('/api/library/papers?trashed=true').json()
    assert trash['total'] == 1 and trash['papers'][0]['id'] == pid
    assert c.get('/api/library/collections').json()['collections'][0]['count'] == 0
    from app.workbench.service import get_workspace, recent
    from app.core.db import get_conn
    with get_conn(settings) as db:
        assert get_workspace(db, 'a'*32)['tabs'] == []
        assert get_workspace(db, 'a'*32)['active_paper_id'] is None
        assert recent(db)['recent'] == []
    from agent_runner.tools import library_search
    assert library_search('Keep', str(settings.db_path))['papers'] == []
    assert library_search('Keep', str(settings.db_path))['excerpts'] == []
    assert c.get(f'/api/sessions/{sid}').status_code == 200
    assert c.post('/api/agent/runs', json={'conversation_id': sid, 'prompt': 'blocked'}).status_code == 409
    assert c.post('/api/sessions', json={'template_id': 'read', 'paper_ids': [pid]}).status_code == 400
    assert path.read_bytes() == b'%PDF-preserved-test-material'
    assert c.post(f'/api/library/papers/{pid}/restore').status_code == 200
    assert c.post(f'/api/library/papers/{pid}/restore').status_code == 200
    restored = c.get('/api/library/papers').json()['papers'][0]
    assert restored['id'] == pid and restored['collections'][0]['id'] == collection['id']
    assert c.get('/api/library/papers?trashed=true').json()['total'] == 0
    assert c.get('/api/library/collections').json()['collections'][0]['count'] == 1
    with sqlite3.connect(settings.db_path) as db:
        assert db.execute('SELECT count(*) FROM conversation_papers WHERE paper_id=?', (pid,)).fetchone()[0] == 1
        assert db.execute('SELECT content FROM reader_annotations WHERE paper_id=?', (pid,)).fetchone()[0] == 'Keep annotation'
        assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0] == 0
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_active_import_and_run_block_removal(client):
    c, settings = client
    pid = paper(settings)
    sid = c.post('/api/sessions', json={'template_id': 'read', 'paper_ids': [pid]}).json()['session']['id']
    with sqlite3.connect(settings.db_path) as db:
        db.execute("INSERT INTO agent_runs(id,request_key,conversation_id,skill,prompt,status) VALUES ('busy','busy',?,'paper_read','test','queued')", (sid,))
    assert c.delete(f'/api/library/papers/{pid}').status_code == 409
    assert c.get('/api/library/papers').json()['total'] == 1
    with sqlite3.connect(settings.db_path) as db:
        db.execute("UPDATE agent_runs SET status='succeeded' WHERE id='busy'")
        db.execute("INSERT INTO import_requests(id,channel,source_value,target_paper_id,status,request_key) VALUES ('import','url','https://example.org/p.pdf',?,'pending','import')", (pid,))
    assert c.delete(f'/api/library/papers/{pid}').status_code == 409
    assert c.delete('/api/library/papers/9999').status_code == 404


def test_trash_is_scoped_to_authenticated_account_and_csrf(secured):
    c, app = secured
    member, _, admin = user(c, app)
    private_paper(app.state, 'Admin paper')
    assert c.delete('/api/library/papers/1', headers=member).status_code == 404
    assert c.delete('/api/library/papers/1', headers={'Cookie': admin['Cookie']}).status_code == 403
    assert c.delete('/api/library/papers/1', headers=admin).status_code == 200
    assert c.get('/api/library/papers?trashed=true', headers=member).json()['total'] == 0
    assert c.post('/api/library/papers/1/restore', headers=member, json={}).status_code == 404
    assert c.post('/api/library/papers/1/restore', headers=admin, json={}).status_code == 200
