from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Union

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
# WAL needs shared memory, which network file systems (Azure App Service /home) do not support; set DELETE there.
JOURNAL_MODES = ("WAL", "DELETE", "TRUNCATE", "PERSIST")


def _journal_mode() -> str:
    mode = (os.environ.get("SQLITE_JOURNAL_MODE") or "").strip().upper()
    return mode if mode in JOURNAL_MODES else "WAL"


def connect(path: Union[str, Path]) -> sqlite3.Connection:
    """Open the store in autocommit mode; callers manage transactions explicitly."""
    target = str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=%s" % _journal_mode())
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not exists:
        return 0
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"] or 0)


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> int:
    """Apply numbered `NNNN_name.sql` files newer than the stored version; return the new version."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    version = current_version(conn)
    for path in sorted(Path(migrations_dir).glob("[0-9][0-9][0-9][0-9]_*.sql")):
        number = int(path.name[:4])
        if number <= version:
            continue
        script = (
            "BEGIN;\n"
            + path.read_text(encoding="utf-8")
            + "\nINSERT INTO schema_version (version, applied_at) "
            + f"VALUES ({number}, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        version = number
    return current_version(conn)
