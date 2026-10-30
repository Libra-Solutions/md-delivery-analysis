"""QA status numbers for one Jira project, by sprint, month and release.

Read-only over what the Jira sync stores. Rows are keyed by sprint, month or release and never carry
people: ranking testers by bugs found would push them to file fewer bugs.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT = "MD"
WINDOW_START = date(2026, 6, 1)
SPRINT_FIELD = "sprint_10006"  # property name of the Jira Sprint field on this site
SPRINT_PREFIX = "MD Sprint"
TESTED_STATUS = "In QA"
QA_STATUSES = ("In QA", "Ready for QA")
BOUNCE_STATUSES = ("In Progress", "To Do", "Code Review")


def ratio(part: float, whole: float) -> Optional[float]:
    return part / whole if whole else None


def key_order(key: str) -> Tuple[str, int]:
    prefix, _, number = key.rpartition("-")
    return (prefix, int(number)) if number.isdigit() else (key, 0)


def _marks(values: Sequence[Any]) -> str:
    return ", ".join("?" for _ in values)


def _project_sprints(value: Optional[str]) -> List[Dict[str, Any]]:
    """The started sprints of this board in a Sprint field value; malformed JSON is no sprint."""
    if not value:
        return []
    try:
        items = json.loads(value)
    except ValueError:
        return []
    if not isinstance(items, list):
        return []
    return [
        s for s in items
        if isinstance(s, dict) and str(s.get("name") or "").startswith(SPRINT_PREFIX) and s.get("startDate")
    ]


def last_sprint(value: Optional[str]) -> Optional[Dict[str, Any]]:
    """The sprint a ticket counts in: the latest-starting one, so carried-over work lands where it finished."""
    sprints = _project_sprints(value)
    return max(sprints, key=lambda s: s["startDate"]) if sprints else None


def _sprint_values(conn: sqlite3.Connection, project: str) -> Dict[str, Optional[str]]:
    rows = conn.execute(
        "SELECT w.source_id, p.value FROM work_item w JOIN property p ON p.record_kind = 'work_item' "
        "AND p.record_id = w.source_id AND p.name = ? WHERE w.source = 'jira' AND w.project = ?",
        (SPRINT_FIELD, project),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def list_sprints(conn: sqlite3.Connection, project: str, start: date, today: date) -> List[Dict[str, Any]]:
    seen: Dict[Any, Dict[str, Any]] = {}
    for value in _sprint_values(conn, project).values():
        for sprint in _project_sprints(value):
            # Tickets fetched at different times can disagree on state; closed is the newest news.
            if sprint["id"] not in seen or sprint.get("state") == "closed":
                seen[sprint["id"]] = sprint
    low, high = start.isoformat(), (today + timedelta(days=1)).isoformat()
    rows = [
        {"sprint_id": s["id"], "name": s["name"], "start": s["startDate"], "end": s.get("endDate"),
         "in_progress": s.get("state") != "closed"}
        for s in seen.values() if low <= s["startDate"] < high
    ]
    return sorted(rows, key=lambda r: r["start"])


def qa_fail_by_sprint(
    conn: sqlite3.Connection, sprints: Sequence[Dict[str, Any]], project: str = PROJECT, start: date = WINDOW_START
) -> Dict[str, Any]:
    """Stories that reached In QA, and those sent back to development from Ready for QA or In QA."""
    tested = conn.execute(
        "SELECT w.source_id, w.key, MIN(t.occurred_at) FROM work_item w JOIN work_item_transition t "
        "ON t.source = w.source AND t.work_item_id = w.source_id AND t.to_status = ? "
        "WHERE w.source = 'jira' AND w.project = ? AND w.type = 'Story' GROUP BY w.source_id, w.key",
        (TESTED_STATUS, project),
    ).fetchall()
    failed = {row[0] for row in conn.execute(
        f"SELECT DISTINCT w.source_id FROM work_item w JOIN work_item_transition t "
        f"ON t.source = w.source AND t.work_item_id = w.source_id "
        f"WHERE w.source = 'jira' AND w.project = ? AND w.type = 'Story' "
        f"AND t.from_status IN ({_marks(QA_STATUSES)}) AND t.to_status IN ({_marks(BOUNCE_STATUSES)})",
        (project, *QA_STATUSES, *BOUNCE_STATUSES),
    )}
    sub_bugs: Dict[str, int] = defaultdict(int)
    for row in conn.execute(
        "SELECT l.to_id, COUNT(DISTINCT s.source_id) FROM work_item s JOIN link l ON l.from_id = s.source_id "
        "AND l.kind = 'parent' WHERE s.source = 'jira' AND s.project = ? AND s.type = 'Sub-bug' GROUP BY l.to_id",
        (project,),
    ):
        sub_bugs[row[0]] = row[1]
    sprint_values = _sprint_values(conn, project)
    stats = {s["sprint_id"]: {"tested": 0, "failed": 0, "failed_keys": [], "sub_bugs_on_tested": 0} for s in sprints}
    unsprinted = 0
    for source_id, key, first_qa in tested:
        sprint = last_sprint(sprint_values.get(source_id))
        if sprint is None:
            if (first_qa or "") >= start.isoformat():
                unsprinted += 1
            continue
        bucket = stats.get(sprint["id"])
        if bucket is None:
            continue
        bucket["tested"] += 1
        bucket["sub_bugs_on_tested"] += sub_bugs[source_id]
        if source_id in failed:
            bucket["failed"] += 1
            bucket["failed_keys"].append(key)
    rows = []
    for sprint in sprints:
        bucket = stats[sprint["sprint_id"]]
        rows.append({
            "sprint_id": sprint["sprint_id"],
            "tested": bucket["tested"],
            "failed": bucket["failed"],
            "fail_rate": ratio(bucket["failed"], bucket["tested"]),
            "failed_keys": sorted(bucket["failed_keys"], key=key_order),
            "sub_bugs_on_tested": bucket["sub_bugs_on_tested"],
            "sub_bugs_per_story": ratio(bucket["sub_bugs_on_tested"], bucket["tested"]),
        })
    return {"rows": rows, "unsprinted_tested": unsprinted}
