from __future__ import annotations
import os

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

    (data / 'old.txt').write_text('unmanaged file')
    (data / 'imports').mkdir()
    (data / 'imports/old.txt').write_text('old managed state')
    return data, backups


def test_restore_requires_explicit_confirmation(tmp_path):
    data, backups = _make_bundle(tmp_path)
    proc = subprocess.run(
        ['sh', str(RESTORE_SH), str(backups), '20261119'],
        env={'PATH': os.environ.get('PATH','/usr/bin:/bin'), 'DATA_DIR': str(data)},
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
        env={'PATH': os.environ.get('PATH','/usr/bin:/bin'), 'DATA_DIR': str(data), 'RESTORE_QDRANT': '0'},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (data / 'app.db').is_file()
    assert (data / 'skills/packages/demo/SKILL.md').read_text() == '# Demo'
    assert (data / 'skills/archives/sha256:demo.zip').read_bytes() == b'zip'
    assert (data / 'avatars/avatar.png').read_bytes() == b'png'
    assert (data / 'old.txt').read_text() == 'unmanaged file'
    assert not (data / 'imports/old.txt').exists()
    rollback = next((data).glob('restore-rollback-*'))
    assert (rollback / 'imports/old.txt').read_text() == 'old managed state'


def test_account_backup_restore_is_complete_and_revokes_sessions(tmp_path):
    if not shutil.which('sqlite3'):
        pytest.skip('sqlite3 CLI unavailable')
    from app.auth.store import AuthStore
    from app.core.config import Settings
    from app.core.db import get_conn
    from test_backup_script import run_backup
    import uuid
    data,backups=_make_bundle(tmp_path)
    auth=AuthStore(data,admin_only=False)
    auth.bootstrap('paper','Private-Admin-Password')
    key=uuid.uuid4().hex;ident=uuid.uuid4().hex
    auth.db.execute("INSERT INTO accounts(id,username,password_hash,role,enabled,workspace_key,created_at) VALUES (?,?,?,'user',1,?,0)",(ident,'reader-one','unused',key));auth.db.commit()
    token,_=auth.issue_session(auth.account(ident))
    settings=Settings(data_dir=data/'accounts'/key,qdrant_url='unused',workspace_key=key)
    db=get_conn(settings)
    (settings.data_dir/'papers').mkdir();(settings.data_dir/'papers/private.pdf').write_bytes(b'%PDF-private-account')
    db.execute('INSERT INTO papers(title,pdf_path) VALUES (?,?)',('WAL committed private paper',f'/app/data/accounts/{key}/papers/private.pdf'));db.commit()
    backup=run_backup(data,backups,'http://127.0.0.1:1');assert backup.returncode==0,backup.stderr
    db.close();auth.close()
    date=__import__('datetime').datetime.now().strftime('%Y%m%d')
    # Root compatibility bundle is fixed-date in the legacy fixture.
    for f in list(backups.glob('*-20261119.*')):
        if date!='20261119':shutil.copyfile(f,f.with_name(f.name.replace('20261119',date)))
    identity=backups/f'identity-{date}.db';assert identity.is_file() and identity.stat().st_mode & 0o077==0
    archive=backups/f'accounts-{date}.tar.gz';assert archive.is_file()
    proc=subprocess.run(['sh',str(RESTORE_SH),str(backups),date,'--confirm'],env={**os.environ,'DATA_DIR':str(data),'RESTORE_QDRANT':'0'},capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    restored=AuthStore(data,admin_only=False)
    assert restored.session(token) is None
    assert restored.account(ident)['workspace_key']==key
    with sqlite3.connect(data/'accounts'/key/'app.db') as restored_db:
        assert restored_db.execute('SELECT title FROM papers').fetchone()[0]=='WAL committed private paper'
    assert (data/'accounts'/key/'papers/private.pdf').read_bytes()==b'%PDF-private-account'
    restored.close()


def test_admin_only_backup_still_has_an_empty_accounts_bundle(tmp_path):
    if not shutil.which('sqlite3'):
        pytest.skip('sqlite3 CLI unavailable')
    from app.auth.store import AuthStore
    from test_backup_script import run_backup
    import datetime
    data=tmp_path/'data';data.mkdir();backups=tmp_path/'backups'
    store=AuthStore(data);store.bootstrap('paper','Private-Admin-Password');store.close()
    result=run_backup(data,backups,'http://127.0.0.1:1')
    assert result.returncode==0,result.stderr
    date=datetime.datetime.now().strftime('%Y%m%d')
    assert (backups/f'identity-{date}.db').is_file()
    with tarfile.open(backups/f'accounts-{date}.tar.gz','r:gz') as bundle:
        assert 'accounts' in bundle.getnames()


def test_restore_checks_all_immutable_versions_before_replacing_data(tmp_path):
    if not shutil.which('sqlite3'):
        pytest.skip('sqlite3 CLI unavailable')
    data,backups=_make_bundle(tmp_path)
    with sqlite3.connect(backups/'app-20261119.db') as db:
        db.execute('CREATE TABLE file_objects(storage_key TEXT PRIMARY KEY)')
        db.execute("INSERT INTO file_objects VALUES ('blob-old-revision.pdf')")
    env={**os.environ,'DATA_DIR':str(data),'RESTORE_QDRANT':'0'}
    first=subprocess.run(['sh',str(RESTORE_SH),str(backups),'20261119','--confirm'],env=env,capture_output=True,text=True)
    assert first.returncode!=0 and 'Missing document version PDF' in first.stderr
    assert (data/'imports/old.txt').is_file()
    root=tmp_path/'papers';root.mkdir();(root/'blob-old-revision.pdf').write_bytes(b'%PDF historical bytes')
    with tarfile.open(backups/'papers-20261119.tar.gz','w:gz') as tar:tar.add(root,arcname='papers')
    second=subprocess.run(['sh',str(RESTORE_SH),str(backups),'20261119','--confirm'],env=env,capture_output=True,text=True)
    assert second.returncode==0,second.stderr
    assert (data/'papers/blob-old-revision.pdf').read_bytes()==b'%PDF historical bytes'


def test_restore_requires_runner_key_and_preserves_connection_transcripts(tmp_path):
    if not shutil.which('sqlite3'):pytest.skip('sqlite3 CLI unavailable')
    data,backups=_make_bundle(tmp_path)
    with sqlite3.connect(backups/'app-20261119.db') as db:
        db.executescript('CREATE TABLE runner_connections(id TEXT);INSERT INTO runner_connections VALUES ("custom");')
    env={**os.environ,'DATA_DIR':str(data),'RESTORE_QDRANT':'0'}
    args=['sh',str(RESTORE_SH),str(backups),'20261119','--confirm']
    failed=subprocess.run(args,env=env,capture_output=True,text=True)
    assert failed.returncode!=0 and 'credential key missing' in failed.stderr
    assert (data/'imports/old.txt').exists()
    source=tmp_path/'source'
    (source/'auth').mkdir(parents=True);(source/'auth/runner-master.key').write_bytes(b'k'*32)
    transcript=source/'agent/connections/custom/claude-config/projects/session.jsonl'
    transcript.parent.mkdir(parents=True);transcript.write_text('custom transcript')
    with tarfile.open(backups/'runner-secrets-20261119.tar.gz','w:gz') as tar:tar.add(source/'auth/runner-master.key',arcname='auth/runner-master.key')
    with tarfile.open(backups/'agent-sessions-20261119.tar.gz','w:gz') as tar:tar.add(source/'agent',arcname='agent')
    ok=subprocess.run(args,env=env,capture_output=True,text=True)
    assert ok.returncode==0,ok.stderr
    assert (data/'auth/runner-master.key').read_bytes()==b'k'*32
    assert (data/'agent/connections/custom/claude-config/projects/session.jsonl').read_text()=='custom transcript'
