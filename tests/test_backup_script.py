"""End-to-end tests for ops/backup.sh.

Runs the real shell script in a sandboxed temp environment:

- local retention (Finding 1): 20 fake backup files per kind -> only the
  newest KEEP=14 survive;
- qdrant lifecycle (Finding 2): against a fake Qdrant HTTP server, verify
  today's snapshot is downloaded and all but the newest 14 server-side
  snapshots are DELETEd.

NOTE: the sqlite branch needs the sqlite3 CLI, which the dev host may not
have (the backup container always does); these tests use a data dir without
app.db, so that branch exercises its graceful-skip path instead.
"""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BACKUP_SH = Path(__file__).resolve().parent.parent / "ops" / "backup.sh"
KEEP = 14


def run_backup(data_dir: Path, backup_dir: Path, qdrant_url: str):
    env = dict(
        os.environ,
        DATA_DIR=str(data_dir),
        BACKUP_DIR=str(backup_dir),
        QDRANT_URL=qdrant_url,
        KEEP=str(KEEP),
    )
    return subprocess.run(
        ["sh", str(BACKUP_SH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class _FakeQdrantHandler(BaseHTTPRequestHandler):
    """Minimal fake of the Qdrant collection/snapshot API surface."""

    def log_message(self, *args):  # keep pytest output clean
        pass

    @property
    def srv(self):
        return self.server

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/readyz":
            self._send({"status": "ok"})
        elif self.path == "/collections":
            self._send({"result": {"collections": [{"name": "papers"}]}})
        elif self.path == "/collections/papers/snapshots":
            self._send({"result": list(self.srv.snapshots)})
        elif self.path.startswith("/collections/papers/snapshots/"):
            self.send_response(200)
            self.send_header("Content-Length", "13")
            self.end_headers()
            self.wfile.write(b"snapshot-data")
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/collections/papers/snapshots":
            self.srv.add_snapshot()
            self._send({"result": {"status": "ok"}})
        else:
            self._send({"error": "not found"}, 404)

    def do_DELETE(self):
        prefix = "/collections/papers/snapshots/"
        if self.path.startswith(prefix):
            name = self.path[len(prefix):]
            ok = self.srv.delete_snapshot(name)
            self._send({"result": {"status": "ok" if ok else "error"}})
        else:
            self._send({"error": "not found"}, 404)


class FakeQdrant(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _FakeQdrantHandler)
        self.snapshots = []
        self.deleted = []

    def add_snapshot(self):
        t = max((s["creation_time_sec"] for s in self.snapshots), default=0) + 1
        self.snapshots.append(
            {"name": f"snap-{t}", "creation_time_sec": t, "size": 100}
        )

    def delete_snapshot(self, name):
        before = len(self.snapshots)
        self.snapshots = [s for s in self.snapshots if s["name"] != name]
        if len(self.snapshots) < before:
            self.deleted.append(name)
            return True
        return False


@pytest.fixture()
def fake_qdrant():
    srv = FakeQdrant()
    for _ in range(16):
        srv.add_snapshot()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _make_backup_dir(tmp_path):
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    data_dir.mkdir()
    backup_dir.mkdir()
    return data_dir, backup_dir


def test_local_prune_keeps_newest_14(tmp_path):
    data_dir, backup_dir = _make_backup_dir(tmp_path)

    n = 20
    for i in range(1, n + 1):
        db = backup_dir / f"app-202501{i:02d}.db"
        db.write_bytes(b"x")
        subprocess.run(
            ["touch", "-d", f"2025-01-01 00:{i:02d}:00", str(db)], check=True
        )
        snap = backup_dir / f"qdrant-papers-202501{i:02d}.snap"
        snap.write_bytes(b"x")
        subprocess.run(
            ["touch", "-d", f"2025-01-01 01:{i:02d}:00", str(snap)], check=True
        )

    # QDRANT_URL unreachable -> exercises the local-prune path only.
    proc = run_backup(data_dir, backup_dir, "http://127.0.0.1:1")
    assert proc.returncode == 0, proc.stderr

    remaining_db = sorted(p.name for p in backup_dir.glob("app-*.db"))
    remaining_snap = sorted(p.name for p in backup_dir.glob("qdrant-*.snap"))
    # newest 14 of 20 by mtime = days 07..20
    expected = sorted(f"app-202501{i:02d}.db" for i in range(7, 21))
    assert remaining_db == expected
    assert len(remaining_snap) == KEEP
    # the 6 oldest files are really gone
    assert not (backup_dir / "app-20250101.db").exists()
    assert not (backup_dir / "qdrant-papers-20250106.snap").exists()


def test_qdrant_server_snapshots_pruned(tmp_path, fake_qdrant):
    data_dir, backup_dir = _make_backup_dir(tmp_path)

    url = f"http://127.0.0.1:{fake_qdrant.server_port}"
    proc = run_backup(data_dir, backup_dir, url)
    assert proc.returncode == 0, proc.stderr

    # script POSTed one new snapshot: 16 seeded + 1 = 17 -> keep 14, delete 3
    assert fake_qdrant.deleted == ["snap-1", "snap-2", "snap-3"]
    assert len(fake_qdrant.snapshots) == KEEP
    # the newest snapshot was downloaded to the local backup dir
    downloads = list(backup_dir.glob("qdrant-papers-*.snap"))
    assert len(downloads) == 1
    assert downloads[0].read_bytes() == b"snapshot-data"


def test_qdrant_server_prune_noop_when_under_limit(tmp_path, fake_qdrant):
    # shrink to 3 snapshots, then run: 3 + 1 created = 4 <= KEEP -> no deletes
    for s in list(fake_qdrant.snapshots):
        if s["creation_time_sec"] > 3:
            fake_qdrant.delete_snapshot(s["name"])
    assert len(fake_qdrant.snapshots) == 3
    fake_qdrant.deleted.clear()  # discard deletions made by this setup itself

    data_dir, backup_dir = _make_backup_dir(tmp_path)
    url = f"http://127.0.0.1:{fake_qdrant.server_port}"
    proc = run_backup(data_dir, backup_dir, url)
    assert proc.returncode == 0, proc.stderr

    assert fake_qdrant.deleted == []
    assert len(fake_qdrant.snapshots) == 4


def test_native_sessions_are_archived_with_private_permissions(tmp_path):
    import tarfile
    data=tmp_path/'data';backups=tmp_path/'backups'
    (data/'agent/claude-config/projects').mkdir(parents=True)
    (data/'agent/sessions/example').mkdir(parents=True)
    (data/'agent/claude-config/projects/session.jsonl').write_text('native transcript')
    (data/'agent/sessions/example/context.txt').write_text('workspace')
    result=run_backup(data,backups,'http://127.0.0.1:1')
    assert result.returncode==0,result.stderr
    archive=next(backups.glob('agent-sessions-*.tar.gz'))
    assert archive.stat().st_mode & 0o077 == 0
    with tarfile.open(archive) as tar:
        assert 'agent/claude-config/projects/session.jsonl' in tar.getnames()
        assert 'agent/sessions/example/context.txt' in tar.getnames()
