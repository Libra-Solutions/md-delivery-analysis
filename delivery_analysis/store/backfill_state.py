"""How far back a finished backfill reached, per source and scope."""

from __future__ import annotations

import sqlite3
from typing import Optional


def get_since(conn: sqlite3.Connection, connector: str, scope: str) -> Optional[str]:
    row = conn.execute(
        "SELECT since FROM backfill_state WHERE connector = ? AND scope = ?", (connector, scope)
    ).fetchone()
    return row["since"] if row else None


def get_range(conn: sqlite3.Connection, connector: str, scope: str) -> Optional[tuple]:
    """(since, done_at): the stretch the finished backfill fetched, or None."""
    row = conn.execute(
        "SELECT since, done_at FROM backfill_state WHERE connector = ? AND scope = ?", (connector, scope)
    ).fetchone()
    return (row["since"], row["done_at"]) if row else None


def mark_done(conn: sqlite3.Connection, connector: str, scope: str, since: str, now: str) -> None:
    """Record that [since, now] is fetched. An earlier start is kept only when the old range reaches this one,
    so the stored range never spans a hole."""
    with conn:
        conn.execute(
            "INSERT INTO backfill_state (connector, scope, since, done_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(connector, scope) DO UPDATE SET "
            "since = CASE WHEN backfill_state.done_at >= excluded.since "
            "THEN min(backfill_state.since, excluded.since) ELSE excluded.since END, "
            "done_at = excluded.done_at",
            (connector, scope, since, now),
        )
