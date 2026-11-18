"""SQLite access layer.

Every connection is opened in WAL mode with foreign keys ON. Pending
migrations in ``app/migrations/*.sql`` are applied automatically in
filename order (tracked in the ``schema_migrations`` table).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _apply_migration(conn: sqlite3.Connection, path: Path) -> None:
    """Apply one migration file atomically, bookkeeping included.

    The script text runs inside an explicit ``BEGIN IMMEDIATE`` (grabbing
    the write lock up front), and the ``schema_migrations`` row is inserted
    into that *same* transaction before the ``COMMIT`` — so a migration is
    either fully applied and recorded, or not applied and not recorded.
    Without this, a script dying mid-way (e.g. 0002 crashing somewhere
    after its first ``ALTER TABLE``) left the schema half-migrated *and*
    unrecorded, so the next start re-ran it into "duplicate column" errors
    with no way back. ``executescript`` never triggers the module's implicit
    COMMIT mid-script here because the pending transaction is cleared before
    the call (Python 3.12's executescript has no implicit pre-COMMIT at
    all; on older interpreters ``conn.commit()`` below disarms it).
    """
    sql = path.read_text(encoding="utf-8")
    conn.commit()  # a pending transaction would make BEGIN IMMEDIATE fail
    # Table-rebuild migrations (SQLite 12-step ALTER) must run with foreign
    # keys OFF; the pragma is a no-op inside a transaction, so toggle it
    # around the script. Migration scripts are trusted DDL.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.executescript(f"BEGIN IMMEDIATE;\n{sql}")
        conn.execute(
            "INSERT INTO schema_migrations (name) VALUES (?)", (path.name,)
        )
        conn.commit()  # COMMITs the transaction the script prefix opened
    except Exception:
        conn.rollback()  # undo every statement the script already ran
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _ensure_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()  # keep this bookkeeping out of the migration transactions
    applied = {
        row[0]
        for row in conn.execute("SELECT name FROM schema_migrations")
    }
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        _apply_migration(conn, path)


def get_conn(settings: Settings | None = None) -> sqlite3.Connection:
    """Open a connection to the app database, running pending migrations.

    ``check_same_thread=False`` does NOT make one connection safe to share
    across threads: SQLite still serializes transactions itself, but the
    *caller* is responsible for not interleaving them (two threads
    committing on the same connection can commit each other's half-written
    transactions). Async code hands connections to ``asyncio.to_thread``
    workers — a single event loop awaiting its own to_thread calls serializes
    fine, but background jobs and multi-threaded scenarios must each open a
    *dedicated* connection (see the P1/P2 job routes and the compare route
    for the pattern: ``get_conn()`` … ``try/finally close()``).
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
