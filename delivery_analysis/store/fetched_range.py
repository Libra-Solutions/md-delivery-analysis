"""Date ranges a sync has fetched per source and scope, kept merged so the stored ranges never overlap."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"
# Ranges this close together count as touching.
TOUCH = timedelta(days=1)

Range = Tuple[str, str]


def parse(value: str) -> datetime:
    """An ISO date or timestamp as an aware UTC datetime."""
    text = value.strip().replace("Z", "+00:00")
    if len(text) == 10:
        text += "T00:00:00+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_ISO_Z)


def merge(ranges: Sequence[Range]) -> List[Range]:
    """Sort and join ranges that overlap or touch (within a day)."""
    spans = sorted((parse(a), parse(b)) for a, b in ranges if a and b and parse(a) <= parse(b))
    out: List[List[datetime]] = []
    for first, last in spans:
        if out and first <= out[-1][1] + TOUCH:
            out[-1][1] = max(out[-1][1], last)
        else:
            out.append([first, last])
    return [(iso(a), iso(b)) for a, b in out]


def first_gap(ranges: Sequence[Range], since: str, until: str) -> Optional[str]:
    """The start of the first stretch of [since, until] no range covers, or None when it is all covered."""
    point, end = parse(since), parse(until)
    for first, last in merge(ranges):
        a, b = parse(first), parse(last)
        if b < point:
            continue
        if a > point + TOUCH:
            break
        point = max(point, b)
        if point + TOUCH >= end:
            return None
    return None if point + TOUCH >= end else iso(point)


def list_ranges(conn: sqlite3.Connection, connector: str, scope: str) -> List[Range]:
    rows = conn.execute(
        "SELECT first, last FROM fetched_range WHERE connector = ? AND scope = ? ORDER BY first",
        (connector, scope),
    ).fetchall()
    return [(row["first"], row["last"]) for row in rows]


def add(conn: sqlite3.Connection, connector: str, scope: str, first: str, last: str) -> None:
    """Store one fetched range, merged with the ones it touches. Does not manage the transaction."""
    merged = merge(list_ranges(conn, connector, scope) + [(first, last)])
    conn.execute("DELETE FROM fetched_range WHERE connector = ? AND scope = ?", (connector, scope))
    conn.executemany(
        "INSERT INTO fetched_range (connector, scope, first, last) VALUES (?, ?, ?, ?)",
        [(connector, scope, a, b) for a, b in merged],
    )
