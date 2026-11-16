"""Health endpoint + lifespan behaviour (startup sweep, RAG-stack retry)."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_conn
from app.main import create_app


def test_health(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    app = create_app()
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_lifespan_raises_after_rag_retries_exhausted(tmp_path, monkeypatch):
    """Qdrant unreachable → bounded retries, then the lifespan raises so the
    container's restart policy (not a permanently degraded 503 app) recovers."""
    import app.main as main

    class _FakeEmbedder:
        dimension = 4

        def __init__(self, model_name="BAAI/bge-m3"):
            pass

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:1")  # nothing listens
    monkeypatch.setattr(main, "Embedder", _FakeEmbedder)
    monkeypatch.setattr(main, "RAG_STARTUP_ATTEMPTS", 2)
    monkeypatch.setattr(main, "RAG_STARTUP_BACKOFF_S", 0.0)

    with pytest.raises(RuntimeError) as excinfo:
        with TestClient(create_app()):
            pass
    assert "RAG stack" in str(excinfo.value)
    assert excinfo.value.__cause__ is not None


def test_lifespan_marks_stale_import_jobs_failed(tmp_path, monkeypatch, embedder):
    """Jobs left pending/running by a previous process are marked failed at
    startup; already-finished job rows are untouched."""
    import app.main as main

    monkeypatch.setattr(
        main, "Embedder", lambda model_name="BAAI/bge-m3": embedder
    )
    settings = Settings(data_dir=tmp_path, qdrant_url=":memory:")
    conn = get_conn(settings)
    conn.execute(
        "INSERT INTO import_jobs (path, total, status) VALUES ('/a', 1, 'running')"
    )
    conn.execute(
        "INSERT INTO import_jobs (path, total, status) VALUES ('/b', 1, 'pending')"
    )
    conn.execute(
        "INSERT INTO import_jobs (path, total, status) VALUES ('/c', 1, 'completed')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QDRANT_URL", ":memory:")
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200

    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        statuses = [row["status"] for row in conn.execute(
            "SELECT status FROM import_jobs ORDER BY id"
        )]
    finally:
        conn.close()
    assert statuses == ["failed", "failed", "completed"]
