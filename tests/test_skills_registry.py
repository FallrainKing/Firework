from __future__ import annotations

import io
import json
import zipfile

import pytest

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_conn
from app.main import create_app


def _zip_bytes(*, manifest: bool = True, version: str = '1.0.0', prompt: str = 'Please review the method.') -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('demo/SKILL.md', '# Demo skill\n\nDo useful work.')
        zf.writestr('demo/templates/prompt.md', prompt)
        if manifest:
            zf.writestr(
                'demo/skill.json',
                json.dumps(
                    {
                        'name': 'Demo',
                        'description': 'Demo skill',
                        'version': version,
                        'requested_tools': ['library_search'],
                        'templates': [{'name': 'Demo prompt', 'file': 'templates/prompt.md'}],
                    }
                ),
            )
    return buf.getvalue()


def _client(tmp_path):
    settings = Settings(data_dir=tmp_path, qdrant_url='http://localhost')
    app = create_app()
    app.state.settings = settings
    app.state.db = get_conn(settings)
    return TestClient(app)


def test_skill_import_install_and_enable(tmp_path):
    client = _client(tmp_path)
    response = client.post('/api/skills/imports', files={'archive': ('demo.zip', _zip_bytes(), 'application/zip')})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['status'] == 'awaiting_config'
    import_id = data['import_id']
    assert data['manifest']['name'] == 'Demo'

    install = client.post(
        f'/api/skills/imports/{import_id}/install',
        json={'name': 'Demo skill', 'description': 'Demo skill', 'category_names': ['阅读理解'], 'budget_profile': 'short'},
    )
    assert install.status_code == 200, install.text
    installed = install.json()
    assert installed['status'] == 'installed'
    assert installed['skill']['source'] == 'zip'
    assert installed['skill']['status'] == 'disabled'
    assert installed['version']['validation_status'] == 'validated'

    skills = client.get('/api/skills', params={'source': 'zip'}).json()['skills']
    assert [s['id'] for s in skills] == [installed['skill']['id']]
    disabled_templates = client.get('/api/sessions/templates').json()
    assert all(t['skill'] != installed['skill']['id'] for t in disabled_templates['templates'])
    assert all(s['id'] != installed['skill']['id'] for s in disabled_templates['skills'])

    enabled = client.post(f"/api/skills/{installed['skill']['id']}/enable").json()
    assert enabled['status'] == 'enabled'
    assert client.get('/api/agent/status').json()['registry_revision'] >= 1

    templates = client.get('/api/sessions/templates').json()
    custom_templates = [t for t in templates['templates'] if t['skill'] == installed['skill']['id']]
    assert len(custom_templates) == 1
    assert custom_templates[0]['prompt'] == 'Please review the method.'
    assert custom_templates[0]['skill_version_id'] == installed['version']['id']
    assert any(s['id'] == installed['skill']['id'] for s in templates['skills'])

    session = client.post(
        '/api/sessions',
        json={'template_id': custom_templates[0]['id'], 'starting_prompt': '请执行演示技能'},
    )
    assert session.status_code == 201, session.text
    assert session.json()['session']['skill'] == installed['skill']['id']
    assert session.json()['session']['skill_version_id'] == installed['version']['id']


def test_skill_version_history_and_default_rollback(tmp_path):
    client = _client(tmp_path)
    upload = client.post('/api/skills/imports', files={'archive': ('demo.zip', _zip_bytes(), 'application/zip')})
    assert upload.status_code == 200, upload.text
    install = client.post(
        f"/api/skills/imports/{upload.json()['import_id']}/install",
        json={'name': 'Demo skill', 'description': 'Demo skill', 'category_names': ['阅读理解'], 'budget_profile': 'short'},
    )
    assert install.status_code == 200, install.text
    installed = install.json()
    skill_id = installed['skill']['id']
    old_version_id = installed['version']['id']

    from app.skills import repository as skills_repo

    db = client.app.state.db
    new_version_id = skills_repo.insert_version(
        db,
        skill_id=skill_id,
        version='1.1.0',
        content_hash='sha256:new-version',
        storage_key='packages/sha256:new-version',
        entry='SKILL.md',
        manifest_json='{"version":"1.1.0"}',
    )
    skills_repo.set_default_version(db, skill_id, new_version_id)
    db.commit()

    enabled = client.post(f'/api/skills/{skill_id}/enable')
    assert enabled.status_code == 200, enabled.text
    hidden_templates = client.get('/api/sessions/templates').json()['templates']
    assert all(template['skill'] != skill_id for template in hidden_templates)

    history = client.get(f'/api/skills/{skill_id}/versions')
    assert history.status_code == 200, history.text
    history_data = history.json()
    assert history_data['default_version_id'] == new_version_id
    assert [(v['version'], v['is_default']) for v in history_data['versions']] == [
        ('1.1.0', True),
        ('1.0.0', False),
    ]
    old_history = next(v for v in history_data['versions'] if v['id'] == old_version_id)
    assert old_history['references'] == {'sessions': 0, 'runs': 0, 'templates': 1}

    detail = client.get(f'/api/skills/{skill_id}')
    assert detail.status_code == 200
    stale = client.post(
        f'/api/skills/{skill_id}/default-version',
        json={'version_id': old_version_id, 'expected_revision': detail.json()['revision'] + 1},
    )
    assert stale.status_code == 409
    assert 'revision' in stale.json()['detail'].lower()

    rollback = client.post(
        f'/api/skills/{skill_id}/default-version',
        json={'version_id': old_version_id, 'expected_revision': detail.json()['revision']},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()['default_version_id'] == old_version_id

    audit = db.execute(
        "SELECT * FROM skill_audit WHERE skill_id=? AND action='default-version' ORDER BY id DESC",
        (skill_id,),
    ).fetchone()
    assert audit['version_id'] == old_version_id
    assert json.loads(audit['detail_json'])['previous_version_id'] == new_version_id

    visible_templates = client.get('/api/sessions/templates').json()['templates']
    assert any(template['skill'] == skill_id for template in visible_templates)


def test_skill_version_resources_and_audit(tmp_path):
    client = _client(tmp_path)
    upload = client.post('/api/skills/imports', files={'archive': ('demo.zip', _zip_bytes(), 'application/zip')})
    install = client.post(
        f"/api/skills/imports/{upload.json()['import_id']}/install",
        json={'name': 'Demo skill', 'description': 'Demo skill', 'category_names': ['阅读理解'], 'budget_profile': 'short'},
    )
    assert install.status_code == 200, install.text
    installed = install.json()
    skill_id = installed['skill']['id']
    version_id = installed['version']['id']

    resources = client.get(f'/api/skills/{skill_id}/versions/{version_id}/resources')
    assert resources.status_code == 200, resources.text
    resource_data = resources.json()
    paths = [item['path'] for item in resource_data['resources']]
    assert paths == ['SKILL.md', 'skill.json', 'templates/prompt.md']
    assert resource_data['resources'][0]['is_entry'] is True

    content = client.get(
        f'/api/skills/{skill_id}/versions/{version_id}/resources/content',
        params={'path': 'templates/prompt.md'},
    )
    assert content.status_code == 200, content.text
    assert content.json()['content'] == 'Please review the method.'

    traversal = client.get(
        f'/api/skills/{skill_id}/versions/{version_id}/resources/content',
        params={'path': '../outside.md'},
    )
    assert traversal.status_code == 404
    assert 'relative paths' in traversal.json()['detail']

    enabled = client.post(f'/api/skills/{skill_id}/enable')
    assert enabled.status_code == 200
    audit = client.get(f'/api/skills/{skill_id}/audit')
    assert audit.status_code == 200, audit.text
    audit_data = audit.json()['audit']
    assert [item['action'] for item in audit_data] == ['enable', 'install']
    assert audit_data[1]['detail']['archive_hash'] == installed['version']['content_hash']


def test_install_new_version_for_existing_skill(tmp_path):
    client = _client(tmp_path)
    first = client.post(
        '/api/skills/imports',
        files={'archive': ('demo.zip', _zip_bytes(), 'application/zip')},
    )
    installed = client.post(
        f"/api/skills/imports/{first.json()['import_id']}/install",
        json={'name': 'Demo skill', 'category_names': ['阅读理解'], 'budget_profile': 'short'},
    ).json()
    skill_id = installed['skill']['id']
    old_version_id = installed['version']['id']

    second = client.post(
        '/api/skills/imports',
        files={'archive': ('demo-v2.zip', _zip_bytes(version='1.1.0', prompt='Review the new method.'), 'application/zip')},
    )
    assert second.status_code == 200, second.text
    upgrade = client.post(
        f"/api/skills/imports/{second.json()['import_id']}/install",
        json={
            'name': 'Demo skill',
            'skill_id': skill_id,
            'budget_profile': 'short',
        },
    )
    assert upgrade.status_code == 200, upgrade.text
    upgraded = upgrade.json()
    assert upgraded['skill']['id'] == skill_id
    assert len(upgraded['skill']['versions']) == 2
    assert upgraded['skill']['default_version_id'] == old_version_id

    conflict_zip = client.post(
        '/api/skills/imports',
        files={'archive': ('demo-conflict.zip', _zip_bytes(version='1.1.0', prompt='Conflict.'), 'application/zip')},
    )
    conflict = client.post(
        f"/api/skills/imports/{conflict_zip.json()['import_id']}/install",
        json={'name': 'Demo skill', 'skill_id': skill_id, 'budget_profile': 'short'},
    )
    assert conflict.status_code == 409
    assert 'version already exists' in conflict.json()['detail']


def test_rejects_path_traversal(tmp_path):
    client = _client(tmp_path)
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, 'w') as zf:
        zf.writestr('../evil/SKILL.md', 'evil')
    response = client.post('/api/skills/imports', files={'archive': ('evil.zip', bad.getvalue(), 'application/zip')})
    assert response.status_code == 422
    assert '路径穿越' in response.json()['detail']


def test_skill_resource_is_version_and_path_scoped(tmp_path, monkeypatch):
    from agent_runner.tools import skill_resource

    package = tmp_path / 'packages' / 'hash'
    package.mkdir(parents=True)
    (package / 'SKILL.md').write_text('# Demo\n', encoding='utf-8')
    (package / 'reference.md').write_text('参考内容', encoding='utf-8')
    monkeypatch.setenv('RESEARCH_SKILL_ROOT', str(package))
    monkeypatch.setenv('RESEARCH_SKILL_HASH', 'sha256:demo')

    got = skill_resource('reference.md')
    assert got['content'] == '参考内容'
    assert got['skill_hash'] == 'sha256:demo'
    assert skill_resource('SKILL.md')['path'] == 'SKILL.md'

    with pytest.raises(ValueError, match='relative paths'):
        skill_resource('../outside.md')
    with pytest.raises(ValueError, match='skill package'):
        skill_resource('/etc/passwd')


def test_skill_validate_run_is_explicit_and_audited(tmp_path, monkeypatch):
    client = _client(tmp_path)
    seen = {}

    async def fake_create_run(body, state):
        seen['skill'] = body.skill
        seen['purpose'] = body.purpose
        seen['prompt'] = body.prompt
        return {
            'id': 'run-validate',
            'status': 'queued',
            'purpose': body.purpose,
            'skill_version_id': 123,
        }

    from app.agent import service as agent_service

    monkeypatch.setattr(agent_service, 'create_run', fake_create_run)
    response = client.post('/api/skills/chat/validate-run', json={'request_key': 'validate-key'})
    assert response.status_code == 202, response.text
    assert seen == {
        'skill': 'chat',
        'purpose': 'skill-validation',
        'prompt': '请执行一次最小技能验证，并简要说明结果。',
    }
    assert response.json()['model_invocation'] is True

    audit = client.get('/api/skills/chat/audit').json()['audit']
    event = next(item for item in audit if item['action'] == 'validate-run')
    assert event['version_id'] == 123
    assert event['detail'] == {'run_id': 'run-validate', 'explicit_model_invocation': True}
