"""Jira sprints: stored from the sprint field on synced issues, and laid out as periods for the AI year page.

Jira keeps each issue's sprints in a custom field (a list of {id, name, state, boardId, startDate, endDate,
completeDate}). The field id differs between sites, so it is found by that shape rather than configured.
A closed sprint ends on its complete date, an open one on its planned end date.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

YEAR_DAYS = 365


def _sprints_in(fields: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for value in fields.values():
        if isinstance(value, list) and value and isinstance(value[0], dict) and "boardId" in value[0] \
                and "startDate" in value[0]:
            yield from (item for item in value if isinstance(item, dict))


def _sprint_row(item: Dict[str, Any]) -> Optional[Tuple[str, str, str, str, str, str]]:
    start = item.get("startDate")
    end = item.get("completeDate") or item.get("endDate")
    if item.get("id") is None or item.get("boardId") is None or not start or not end:
        return None  # a future sprint has no dates yet
    return (str(item["id"]), str(item["boardId"]), str(item.get("name") or item["id"]),
            item.get("state"), str(start), str(end))


def _rank(row: Tuple[str, str, str, str, str, str]) -> Tuple[int, str]:
    """Issues synced at different times hold different snapshots of one sprint: a closed one (with its complete
    date) beats an open one, then the later end wins."""
    return (1 if row[3] == "closed" else 0, row[5])


def derive_sprints(conn: sqlite3.Connection) -> int:
    """Rebuild the sprint tables from the stored Jira issues; returns how many sprints are known."""
    sprints: Dict[str, Tuple[str, str, str, str, str, str]] = {}
    members: List[Tuple[str, str]] = []
    for row in conn.execute("SELECT source_id, json FROM raw_payload WHERE source = 'jira' AND kind = 'issue'"):
        try:
            data = json.loads(row[1])
        except (TypeError, ValueError):
            continue
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else data
        for item in _sprints_in(fields):
            parsed = _sprint_row(item)
            if parsed is None:
                continue
            known = sprints.get(parsed[0])
            if known is None or _rank(parsed) > _rank(known):
                sprints[parsed[0]] = parsed
            members.append((str(row[0]), parsed[0]))
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM work_item_sprint")
        conn.execute("DELETE FROM sprint")
        conn.executemany("INSERT INTO sprint (sprint_id, board_id, name, state, start_at, end_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)", list(sprints.values()))
        conn.executemany("INSERT OR IGNORE INTO work_item_sprint (work_item_id, sprint_id) VALUES (?, ?)", members)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(sprints)


def person_board(conn: sqlite3.Connection, person_id: str, since: date) -> Optional[str]:
    """The board most of this person's credited tickets were sprinted on since `since`; ties go to the
    board with the most recent sprint, then the lowest id."""
    row = conn.execute(
        "SELECT s.board_id AS board, COUNT(DISTINCT c.work_item_id) AS n, MAX(s.start_at) AS last "
        "FROM ticket_credit c JOIN work_item_sprint ws ON ws.work_item_id = c.work_item_id "
        "JOIN sprint s ON s.sprint_id = ws.sprint_id "
        "WHERE c.person_id = ? AND c.work_item_source = 'jira' AND s.end_at >= ? "
        "GROUP BY s.board_id ORDER BY n DESC, last DESC, board LIMIT 1",
        (person_id, since.isoformat()),
    ).fetchone()
    return None if row is None else str(row[0])


def board_name(conn: sqlite3.Connection, board_id: str) -> str:
    """A readable board label from its latest sprint name, for example "MD" from "MD Sprint 87"."""
    row = conn.execute("SELECT name FROM sprint WHERE board_id = ? ORDER BY start_at DESC LIMIT 1",
                       (board_id,)).fetchone()
    if row is None:
        return f"board {board_id}"
    name = str(row[0])
    head = name.split(" Sprint")[0].strip()
    return head if head and head != name else f"board {board_id}"


def _utc(text: str) -> str:
    """A Jira time ("2026-11-05T14:11:56.388Z" or with an offset) as ISO UTC to the second."""
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_day(until: str) -> date:
    """The last calendar day a sprint ending at `until` (exclusive) touches."""
    moment = datetime.strptime(until, "%Y-%m-%dT%H:%M:%SZ") - timedelta(seconds=1)
    return moment.date()


def _now_utc(today: date) -> str:
    """The end of `today`, so a sprint closing after today is still running."""
    return (datetime.combine(today + timedelta(days=1), datetime.min.time())).strftime("%Y-%m-%dT%H:%M:%SZ")


def sprint_blocks(conn: sqlite3.Connection, board_id: str, today: date, anchor: Optional[date],
                  back_days: int = YEAR_DAYS) -> List[Dict[str, Any]]:
    """The board's sprints that overlap the last `back_days` days and have started by today, oldest first.

    Same keys as `ai_year.month_blocks` plus `name`, `last`, and `at` and `until`: the exact UTC times the sprint
    runs from and to, which the numbers use. A sprint ends when it closed (or its planned end), or when the next
    sprint starts if there is a gap. `index` counts sprints from the one holding the AI start (0); with no AI start all
    are negative. The running sprint is partial."""
    first_day = today - timedelta(days=back_days - 1)
    rows = conn.execute(
        "SELECT name, start_at, end_at FROM sprint WHERE board_id = ? AND substr(start_at, 1, 10) <= ? "
        "AND substr(end_at, 1, 10) > ? ORDER BY start_at, sprint_id",
        (board_id, today.isoformat(), first_day.isoformat()),
    ).fetchall()
    # Exact UTC times, as the Director's velocity table cuts sprints: from the start to the close (or planned end).
    spans: List[List[str]] = []
    for name, start_at, end_at in rows:
        start, end = _utc(start_at), _utc(end_at)
        if end <= start:
            continue
        if spans and start < spans[-1][2]:  # overlapping sprints on one board: start after the previous one
            start = spans[-1][2]
            if end <= start:
                continue
        if spans and start > spans[-1][2]:  # time between two sprints belongs to the earlier one, so none is lost
            spans[-1][2] = start
        spans.append([name, start, end])
    zero = len(spans)
    if anchor is not None:
        zero = next((k for k, span in enumerate(spans) if anchor < _local_day(span[2])), len(spans))
    out: List[Dict[str, Any]] = []
    for k, (name, at, until) in enumerate(spans):
        first, close = date.fromisoformat(at[:10]), _local_day(until)
        last = min(close, today)
        length = max((close - first).days + 1, 1)
        seen = max((last - first).days + 1, 1)
        out.append({
            "index": k - zero if anchor is not None else k - len(spans),
            "first": first.isoformat(), "last": last.isoformat(), "name": name, "at": at, "until": until,
            "days": seen, "month_days": length, "partial": until > _now_utc(today),
        })
    return out
