"""Category trees, reversible removal, concurrency and account/source boundaries."""
import sqlite3
from test_agent_mvp import client
from test_task_sessions import paper
from test_auth_accounts import secured, login, user


def create(c, name, parent=None):
    r = c.post('/api/library/collections', json={'name': name, 'parent_id': parent})
    assert r.status_code == 201, r.text
    return r.json()


def trash(c, node, headers=None):
    return c.request('DELETE', f"/api/library/collections/{node['id']}", json={'expected_revision': node['revision']}, headers=headers)


def restore(c, node):
    return c.post(f"/api/library/collections/{node['id']}/restore", json={'expected_revision': node['revision']})


def test_move_rename_and_conflicts_preserve_tree_memberships(client):
    c, settings = client
    a, b = create(c, 'A'), create(c, 'B')
    child = create(c, 'Child', a['id'])
    pid = paper(settings)
    assert c.patch(f'/api/library/papers/{pid}', json={'metadata_version': 1, 'collection_ids': [child['id']]}).status_code == 200
    body = {'name': 'Renamed', 'parent_id': b['id'], 'expected_revision': child['revision']}
    r = c.patch(f"/api/library/collections/{child['id']}", json=body)
    assert r.status_code == 200, r.text
    updated = next(x for x in r.json()['collections'] if x['id'] == child['id'])
    assert updated['path'] == 'B / Renamed'
    assert c.get('/api/library/papers', params={'collection_id': b['id']}).json()['total'] == 1
    assert c.get('/api/library/papers', params={'collection_id': a['id']}).json()['total'] == 0
    assert c.patch(f"/api/library/collections/{child['id']}", json=body).status_code == 409
    assert c.patch(f"/api/library/collections/{b['id']}", json={'name': 'B', 'parent_id': child['id'], 'expected_revision': b['revision']}).status_code == 409
    assert c.patch(f"/api/library/collections/{b['id']}", json={'name': 'B', 'parent_id': b['id'], 'expected_revision': b['revision']}).status_code == 409
    create(c, 'Taken', b['id'])
    assert c.patch(f"/api/library/collections/{child['id']}", json={'name': 'Taken', 'parent_id': b['id'], 'expected_revision': updated['revision']}).status_code == 409
    assert c.get(f'/api/library/papers/{pid}').json()['collections'][0]['id'] == child['id']


def test_trash_restore_preserves_papers_sessions_and_archived_memberships(client):
    c, settings = client
    root = create(c, 'Root'); child = create(c, 'Child', root['id'])
    pid = paper(settings)
    c.patch(f'/api/library/papers/{pid}', json={'metadata_version': 1, 'collection_ids': [child['id']]})
    sid = c.post('/api/sessions', json={'template_id': 'read', 'paper_ids': [pid]}).json()['session']['id']
    assert trash(c, root).status_code == 200
    assert c.get('/api/library/collections').json()['collections'] == []
    assert c.get('/api/library/papers').json()['total'] == 1
    assert c.get('/api/library/papers?collection_id=0').json()['total'] == 1
    current = c.get(f'/api/library/papers/{pid}').json()
    assert current['collections'] == []
    # Editing other paper fields must not erase archived membership evidence.
    c.patch(f'/api/library/papers/{pid}', json={'metadata_version': current['metadata_version'], 'title': 'Updated', 'collection_ids': []})
    deleted = c.get('/api/library/collections?trashed=true').json()['collections']
    assert len(deleted) == 2
    assert next(x for x in deleted if x['id'] == root['id'])['restore_root']
    assert restore(c, next(x for x in deleted if x['id'] == child['id'])).status_code == 409
    assert restore(c, next(x for x in deleted if x['id'] == root['id'])).status_code == 200
    assert c.get(f'/api/library/papers/{pid}').json()['collections'][0]['id'] == child['id']
    assert c.get(f'/api/sessions/{sid}').status_code == 200
    with sqlite3.connect(settings.db_path) as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT count(*) FROM papers').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM agent_runs').fetchone()[0] == 0


def test_restore_conflict_and_separately_deleted_children(client):
    c, _ = client
    root = create(c, 'Root'); old = create(c, 'Old', root['id'])
    assert trash(c, old).status_code == 200
    assert c.get('/api/library/collections').json()['collections'][0]['count'] == 0
    assert trash(c, root).status_code == 200
    deleted = c.get('/api/library/collections?trashed=true').json()['collections']
    root_deleted = next(x for x in deleted if x['id'] == root['id'])
    conflict = create(c, 'Root')
    assert restore(c, root_deleted).status_code == 409
    assert trash(c, conflict).status_code == 200
    assert restore(c, root_deleted).status_code == 200
    assert [x['id'] for x in c.get('/api/library/collections').json()['collections']] == [root['id']]
    assert restore(c, next(x for x in deleted if x['id'] == old['id'])).status_code == 200


def test_managed_sources_and_active_imports_are_protected(client):
    c, settings = client
    with sqlite3.connect(settings.db_path) as db:
        rid = db.execute("INSERT INTO paper_collections(name) VALUES ('Zotero · Device abc123')").lastrowid
        cid = db.execute('INSERT INTO paper_collections(name,parent_id) VALUES (?,?)', ('Reading', rid)).lastrowid
    source = next(x for x in c.get('/api/library/collections').json()['collections'] if x['id'] == cid)
    assert source['managed']
    assert trash(c, source).status_code == 409
    assert c.patch(f'/api/library/collections/{cid}', json={'name': 'Changed', 'parent_id': None, 'expected_revision': 1}).status_code == 409
    assert c.post('/api/library/collections', json={'name': 'Personal', 'parent_id': cid}).status_code == 409
    native = create(c, 'Native')
    assert c.patch(f"/api/library/collections/{native['id']}", json={'name': 'Native', 'parent_id': cid, 'expected_revision': 1}).status_code == 409
    with sqlite3.connect(settings.db_path) as db:
        db.execute("INSERT INTO import_requests(id,request_key,channel,source_value,collection_id) VALUES ('pending','pending','doi','10.1/x',?)", (native['id'],))
    assert trash(c, native).status_code == 409


def test_authenticated_profile_and_cross_account_category_mutation(secured):
    c, app = secured
    admin = login(c)
    profile = c.get('/api/me', headers=admin).json()
    assert profile['capabilities']['auth'] is True
    assert profile['login_policy'] == {'admin_only': True, 'registration_open': False}
    owned = c.post('/api/library/collections', headers=admin, json={'name': 'Admin private'}).json()
    other, _, _ = user(c, app)
    assert c.patch(f"/api/library/collections/{owned['id']}", headers=other, json={'name': 'Stolen', 'parent_id': None, 'expected_revision': 1}).status_code == 404
    assert trash(c, owned, other).status_code == 404
    assert c.request('DELETE', f"/api/library/collections/{owned['id']}", json={'expected_revision': 1}, headers={'Cookie': admin['Cookie']}).status_code == 403
