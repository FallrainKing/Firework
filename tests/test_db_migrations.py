"""Tests for the SQLite layer: get_conn(), WAL/foreign_keys, migrations."""

import sqlite3

import pytest

from app.config import Settings
from app.db import MIGRATIONS_DIR, get_conn

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
        "affiliations",
        "affiliation_source",
        "brief_summary",
        "summary_source",
        "metadata_version",
    }
    # defaults
    assert cols["status"][4] == "'new'"
    assert cols["affiliations"][4] == "'[]'"
    assert cols["metadata_version"][4] == "1"
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
        "kind",  # added by 0002 (P2 Task 5): 'import' | 'interpret'
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
    # existing rows and new rows both default to the P1 import job kind
    assert row["kind"] == "import"


def test_migrations_idempotent(conn):
    conn.close()
    c2 = get_conn()  # second connection must not re-apply / must not fail
    assert "papers" in _tables(c2)
    c2.close()


def test_migration_failure_rolls_back_and_rerun_completes(tmp_path):
    """迁移中途失败必须整体回滚（runner 包 BEGIN IMMEDIATE/COMMIT）。

    人为让 0002 在 ALTER 之后、脚本末尾之前崩掉（预建 notes_new 表 →
    CREATE TABLE notes_new 重复）：失败后 schema 不得留半截状态——
    import_jobs 无 kind 列、schema_migrations 未记账；清障后第二次跑
    真实迁移文件应成功完成而非撞上 "duplicate column name: kind"。
    """
    settings = Settings(data_dir=tmp_path, qdrant_url=":memory:")
    legacy = sqlite3.connect(settings.db_path)
    legacy.executescript((MIGRATIONS_DIR / "0001_init.sql").read_text("utf-8"))
    # replicate the bookkeeping _ensure_migrations did for 0001
    legacy.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    legacy.execute("INSERT INTO schema_migrations (name) VALUES ('0001_init.sql')")
    # the obstacle: 0002 gets past ALTER ... ADD COLUMN kind, then dies at
    # CREATE TABLE notes_new
    legacy.execute("CREATE TABLE notes_new (id INTEGER PRIMARY KEY)")
    legacy.commit()
    legacy.close()

    with pytest.raises(sqlite3.OperationalError, match="notes_new"):
        get_conn(settings)  # 0002 fails midway

    failed = sqlite3.connect(settings.db_path)
    try:
        # no half-migrated state: the ALTER was rolled back and the
        # migration was NOT recorded as applied
        assert (
            "kind"
            not in {r[1] for r in failed.execute("PRAGMA table_info(import_jobs)")}
        )
        assert "0002_jobs_kind_and_notes_sixdim.sql" not in {
            row[0]
            for row in failed.execute("SELECT name FROM schema_migrations")
        }
    finally:
        failed.close()

    # clear the obstacle and re-run the real migration files: the second
    # run must complete (before the fix it died on "duplicate column name:
    # kind" left behind by the un-rolled-back ALTER)
    cleanup = sqlite3.connect(settings.db_path)
    cleanup.execute("DROP TABLE notes_new")
    cleanup.commit()
    cleanup.close()

    conn = get_conn(settings)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_jobs)")}
        assert "kind" in cols
        assert "0002_jobs_kind_and_notes_sixdim.sql" in {
            row[0] for row in conn.execute("SELECT name FROM schema_migrations")
        }
        # six_dim notes are writable again after the successful re-run
        conn.execute("INSERT INTO papers (title, source) VALUES ('t', 'upload')")
        conn.execute(
            "INSERT INTO notes (paper_id, note_type, content)"
            " VALUES (1, 'six_dim', '六维')"
        )
        conn.commit()
    finally:
        conn.close()


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


def test_settings_invalid_llm_providers_json_fails_fast(tmp_path, monkeypatch):
    # a typo'd LLM_PROVIDERS must abort startup, not silently mean "no providers"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("LLM_PROVIDERS", '{"name": "p1",')  # truncated JSON
    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()
    message = str(excinfo.value)
    assert "LLM_PROVIDERS" in message
    # the original parser error travels along for diagnosis
    assert excinfo.value.__cause__ is not None
    assert "Expecting" in str(excinfo.value.__cause__)


def test_settings_llm_providers_non_array_fails_fast(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("LLM_PROVIDERS", '{"name": "p1"}')  # object, not array
    with pytest.raises(ValueError) as excinfo:
        Settings.from_env()
    assert "array" in str(excinfo.value)
