"""Cohort store: which people are tracked, at what level, and their Day 0."""

from __future__ import annotations

import sqlite3
from datetime import date

LEVELS = ("Mid", "Senior")


def set_member(conn: sqlite3.Connection, person_id: str, level: str, day0: str) -> None:
    if level not in LEVELS:
        raise ValueError(f"Level must be Mid or Senior, not {level!r}.")
    try:
        parsed = date.fromisoformat(day0)
    except (TypeError, ValueError):
        raise ValueError(f"Day 0 must be a date like 2026-09-19, not {day0!r}.")
    if parsed.isoformat() != day0:
        raise ValueError(f"Day 0 must be a date like 2026-09-19, not {day0!r}.")
    if conn.execute("SELECT 1 FROM person WHERE person_id = ?", (person_id,)).fetchone() is None:
        raise LookupError(f"No person with id {person_id!r}.")
    with conn:
        conn.execute(
            "INSERT INTO cohort_member (person_id, level, day0) VALUES (?, ?, ?) "
            "ON CONFLICT(person_id) DO UPDATE SET level = excluded.level, day0 = excluded.day0",
            (person_id, level, day0),
        )


def list_members(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT c.person_id AS person_id, p.display_name AS name, c.level AS level, c.day0 AS day0 "
        "FROM cohort_member c JOIN person p ON p.person_id = c.person_id "
        "ORDER BY lower(p.display_name), c.person_id"
    ).fetchall()
    return [dict(row) for row in rows]


def remove_member(conn: sqlite3.Connection, person_id: str) -> bool:
    with conn:
        cursor = conn.execute("DELETE FROM cohort_member WHERE person_id = ?", (person_id,))
    return cursor.rowcount > 0
