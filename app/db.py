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
    """Open a connection to the app database, running pending migrations.

    ``check_same_thread=False``: async code (reader/compare) hands this
    connection to ``asyncio.to_thread`` worker threads. sqlite3's default
    refuses any cross-thread use outright, so without this flag those calls
    die with ProgrammingError the moment they leave the event-loop thread.
    Every caller must still serialize access to one connection (a single
    event loop awaiting its own to_thread calls does that); see Task 5's
    report for the impact assessment.
    """
    s = settings or Settings.from_env()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_migrations(conn)
    return conn
