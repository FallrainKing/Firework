"""Tests for the SQLite layer: get_conn(), WAL/foreign_keys, migrations."""

import sqlite3

import pytest

from app.config import Settings
from app.db import get_conn

EXPECTED_TABLES = {
    "papers",
    "chunks_meta",
    "notes",
    "conversations",
    "import_jobs",
    "push_log",
    "interest_profile",
    "knowledge_map",
    "llm_usage",
    "schema_migrations",
}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    c = get_conn()
    yield c
    c.close()


def _tables(c):
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def test_migrations_create_all_tables(conn):
    assert EXPECTED_TABLES <= _tables(conn)


def test_pragmas(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_papers_schema(conn):
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(papers)")}
    assert set(cols) == {
        "id",
        "arxiv_id",
        "title",
        "authors",
        "abstract",
        "categories",
        "source",
        "status",
        "pdf_path",
        "created_at",
    }
    # defaults
    assert cols["status"][4] == "'new'"
    # CHECK constraints accept valid values and reject invalid ones
    conn.execute(
        "INSERT INTO papers(title, source) VALUES ('t1', 'upload')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO papers(title, source) VALUES ('t2', 'bogus')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO papers(title, source, status)"
            " VALUES ('t3', 'upload', 'nope')"
        )


def test_import_jobs_schema(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(import_jobs)")}
    assert cols == {
        "id",
        "path",
        "total",
        "done",
        "failed",
        "errors",
        "status",
        "created_at",
    }
    conn.execute(
        "INSERT INTO import_jobs(path, total) VALUES ('/x', 3)"
    )
    row = conn.execute("SELECT * FROM import_jobs").fetchone()
    assert row["errors"] == "[]" and row["status"] == "pending"
    assert row["done"] == 0 and row["failed"] == 0


def test_migrations_idempotent(conn):
    conn.close()
    c2 = get_conn()  # second connection must not re-apply / must not fail
    assert "papers" in _tables(c2)
    c2.close()


def test_foreign_key_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO chunks_meta(paper_id, chunk_idx, text)"
            " VALUES (9999, 0, 'x')"
        )


def test_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("LLM_PROVIDERS", '[{"name": "p1", "api_key": "k"}]')
    monkeypatch.setenv("LLM_FAST", "p1")
    monkeypatch.setenv("LLM_STRONG", "p2")
    s = Settings.from_env()
    assert s.data_dir == tmp_path
    assert s.qdrant_url == "http://localhost:6333"
    assert s.llm_providers == [{"name": "p1", "api_key": "k"}]
    assert s.llm_fast == "p1" and s.llm_strong == "p2"
