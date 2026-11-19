from __future__ import annotations

import io
import json
import zipfile

import pytest

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_conn
from app.main import create_app


def _zip_bytes(*, manifest: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('demo/SKILL.md', '# Demo skill\n\nDo useful work.')
        zf.writestr('demo/templates/prompt.md', 'Please review the method.')
        if manifest:
            zf.writestr(
                'demo/skill.json',
                json.dumps(
                    {
                        'name': 'Demo',
                        'description': 'Demo skill',
                        'version': '1.0.0',
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
