from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import get_conn
from app.main import create_app


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0aIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _client(tmp_path):
    settings = Settings(data_dir=tmp_path, qdrant_url='http://localhost')
    app = create_app()
    app.state.settings = settings
    app.state.db = get_conn(settings)
    return TestClient(app)


def test_local_profile_defaults_and_update(tmp_path):
    client = _client(tmp_path)
    response = client.get('/api/me')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['display_name'] == '本地研究用户'
    assert data['auth_mode'] == 'local'
    assert data['avatar_url'] is None
    assert data['capabilities'] == {
        'auth': False,
        'avatar_upload': True,
        'preferences': True,
        'skills': True,
    }

    updated = client.patch('/api/me', json={'display_name': '研究者'})
    assert updated.status_code == 200, updated.text
    assert updated.json()['display_name'] == '研究者'
    assert updated.json()['revision'] > data['revision']

    empty = client.patch('/api/me', json={'display_name': ' '})
    assert empty.status_code == 422
    assert 'empty' in empty.json()['detail']


def test_avatar_upload_validation_and_serving(tmp_path):
    client = _client(tmp_path)
    invalid_type = client.post('/api/me/avatar', files={'avatar': ('avatar.gif', GIF := b'GIF89a', 'image/gif')})
    assert invalid_type.status_code == 422
    assert 'PNG, JPEG, or WebP' in invalid_type.json()['detail']

    forged = client.post('/api/me/avatar', files={'avatar': ('avatar.png', b'not-a-png', 'image/png')})
    assert forged.status_code == 422
    assert 'does not match' in forged.json()['detail']

    too_large = PNG + b'0' * (2 * 1024 * 1024 - len(PNG) + 1)
    oversized = client.post('/api/me/avatar', files={'avatar': ('avatar.png', too_large, 'image/png')})
    assert oversized.status_code == 422
    assert '2MB' in oversized.json()['detail']

    uploaded = client.post('/api/me/avatar', files={'avatar': ('avatar.png', PNG, 'image/png')})
    assert uploaded.status_code == 200, uploaded.text
    data = uploaded.json()
    assert data['avatar_url'].startswith('/api/me/avatar/')
    avatar = client.get(data['avatar_url'])
    assert avatar.status_code == 200
    assert avatar.content == PNG
    assert avatar.headers['content-type'] == 'image/png'
    assert not (tmp_path / 'avatars' / 'avatar.png').exists()

    missing = client.get('/api/me/avatar/not-a-valid-key')
    assert missing.status_code == 404


def test_preferences_revision_conflict(tmp_path):
    client = _client(tmp_path)
    initial = client.get('/api/me/preferences')
    assert initial.status_code == 200
    assert initial.json() == {'preferences': {}, 'revision': 0}

    updated = client.patch(
        '/api/me/preferences',
        json={'preferences': {'theme': 'dark'}, 'expected_revision': None},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()['preferences'] == {'theme': 'dark'}
    assert updated.json()['revision'] == 1

    conflict = client.patch(
        '/api/me/preferences',
        json={'preferences': {'theme': 'light'}, 'expected_revision': 2},
    )
    assert conflict.status_code == 409
    assert 'revision mismatch' in conflict.json()['detail']
