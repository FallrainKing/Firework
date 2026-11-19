from __future__ import annotations

import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

RESTORE_SH = Path(__file__).resolve().parent.parent / 'ops' / 'restore.sh'


def _make_bundle(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / 'data'
    backups = tmp_path / 'backups'
    data.mkdir()
    backups.mkdir()
    db = backups / 'app-20261119.db'
    conn = sqlite3.connect(db)
    conn.executescript('''
      CREATE TABLE skill_versions(id INTEGER PRIMARY KEY, storage_key TEXT NOT NULL);
      CREATE TABLE skill_imports(id INTEGER PRIMARY KEY, archive_hash TEXT NOT NULL);
      CREATE TABLE user_profile(singleton_id INTEGER PRIMARY KEY, avatar_storage_key TEXT NOT NULL);
      CREATE TABLE agent_runs(id TEXT PRIMARY KEY, skill_version_id INTEGER, status TEXT NOT NULL);
      CREATE TABLE conversations(id INTEGER PRIMARY KEY, skill_version_id INTEGER);
      INSERT INTO skill_versions VALUES (1, 'packages/demo');
      INSERT INTO skill_imports VALUES (1, 'sha256:demo');
      INSERT INTO user_profile VALUES (1, 'avatar.png');
    ''')
    conn.commit()
    conn.close()

    skills_root = tmp_path / 'skills-source/skills'
    (skills_root / 'packages/demo').mkdir(parents=True)
    (skills_root / 'archives').mkdir()
    (skills_root / 'packages/demo/SKILL.md').write_text('# Demo')
    (skills_root / 'archives/sha256:demo.zip').write_bytes(b'zip')
    with tarfile.open(backups / 'skills-20261119.tar.gz', 'w:gz') as tar:
        tar.add(skills_root, arcname='skills')

    avatar_root = tmp_path / 'avatars-source/avatars'
    avatar_root.mkdir(parents=True)
    (avatar_root / 'avatar.png').write_bytes(b'png')
    with tarfile.open(backups / 'avatars-20261119.tar.gz', 'w:gz') as tar:
        tar.add(avatar_root, arcname='avatars')

    (data / 'old.txt').write_text('old state')
    return data, backups


def test_restore_requires_explicit_confirmation(tmp_path):
    data, backups = _make_bundle(tmp_path)
    proc = subprocess.run(
        ['sh', str(RESTORE_SH), str(backups), '20261119'],
        env={'PATH': '/usr/bin:/bin:/usr/local/bin', 'DATA_DIR': str(data)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert (data / 'old.txt').exists()


def test_restore_validates_skill_bundle_and_replaces_state(tmp_path):
    if not shutil.which('sqlite3'):
        pytest.skip('sqlite3 CLI unavailable')
    data, backups = _make_bundle(tmp_path)
    proc = subprocess.run(
        ['sh', str(RESTORE_SH), str(backups), '20261119', '--confirm'],
        env={'PATH': '/usr/bin:/bin:/usr/local/bin', 'DATA_DIR': str(data), 'RESTORE_QDRANT': '0'},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (data / 'app.db').is_file()
    assert (data / 'skills/packages/demo/SKILL.md').read_text() == '# Demo'
    assert (data / 'skills/archives/sha256:demo.zip').read_bytes() == b'zip'
    assert (data / 'avatars/avatar.png').read_bytes() == b'png'
    assert not (data / 'old.txt').exists()
    rollback = next((data).glob('restore-rollback-*'))
    assert (rollback / 'old.txt').exists()
