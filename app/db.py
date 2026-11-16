"""SQLite access layer.

Every connection is opened in WAL mode with foreign keys ON. Pending
migrations in ``app/migrations/*.sql`` are applied automatically in
filename order (tracked in the ``schema_migrations`` table).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _ensure_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row[0]
        for row in conn.execute("SELECT name FROM schema_migrations")
    }
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (name) VALUES (?)", (path.name,)
        )
        conn.commit()


def get_conn(settings: Settings | None = None) -> sqlite3.Connection:
    """Open a connection to the app database, running pending migrations."""
    s = settings or Settings.from_env()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_migrations(conn)
    return conn
