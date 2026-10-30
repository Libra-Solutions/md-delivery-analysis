"""QA status numbers for one Jira project, by sprint, month and release.

Read-only over what the Jira sync stores. Rows are keyed by sprint, month or release and never carry
people: ranking testers by bugs found would push them to file fewer bugs.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone, tzinfo
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


ESCAPED_TYPE = "Defect"
FOUND_TYPES = {"Defect": "defects", "Bug": "bugs", "Sub-bug": "sub_bugs"}
ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def _found_tickets(conn: sqlite3.Connection, project: str) -> List[Tuple[str, str, str]]:
    types = list(FOUND_TYPES)
    return [tuple(row) for row in conn.execute(
        f"SELECT key, type, created_at FROM work_item WHERE source = 'jira' AND project = ? "
        f"AND type IN ({_marks(types)}) AND created_at IS NOT NULL",
        (project, *types),
    )]


def _escape(tickets: Sequence[Tuple[str, str, str]]) -> Dict[str, Any]:
    counts = {name: 0 for name in FOUND_TYPES.values()}
    defect_keys = []
    for key, type_, _ in tickets:
        counts[FOUND_TYPES[type_]] += 1
        if type_ == ESCAPED_TYPE:
            defect_keys.append(key)
    found = sum(counts.values())
    return {**counts, "found": found, "escape_rate": ratio(counts["defects"], found),
            "defect_keys": sorted(defect_keys, key=key_order)}


def escape_rate_by_sprint(
    conn: sqlite3.Connection, sprints: Sequence[Dict[str, Any]], project: str = PROJECT
) -> List[Dict[str, Any]]:
    """Defects / (Defects + Bugs + Sub-bugs) created between each sprint's start and end."""
    tickets = _found_tickets(conn, project)
    rows = []
    for sprint in sprints:
        inside = [t for t in tickets if t[2] >= sprint["start"] and (not sprint["end"] or t[2] < sprint["end"])]
        rows.append({"sprint_id": sprint["sprint_id"], **_escape(inside)})
    return rows


def _local_month(iso: str, tz: tzinfo) -> str:
    return datetime.strptime(iso, ISO_Z).replace(tzinfo=timezone.utc).astimezone(tz).strftime("%Y-%m")


def escape_rate_by_month(
    conn: sqlite3.Connection, project: str, start: date, today: date, tz: tzinfo
) -> List[Dict[str, Any]]:
    months = []
    cursor = date(start.year, start.month, 1)
    while cursor <= today:
        months.append(cursor.strftime("%Y-%m"))
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    buckets: Dict[str, List[Tuple[str, str, str]]] = {month: [] for month in months}
    for t in _found_tickets(conn, project):
        month = _local_month(t[2], tz)
        if month in buckets:
            buckets[month].append(t)
    return [{"month": month, **_escape(buckets[month])} for month in months]


REGRESSION_STORY_TYPE = "Story"
REGRESSION_TITLE = re.compile(r"^\s*(\d+\.\d+)\s+regression\b", re.IGNORECASE)
REGRESSION_BUG_TYPE = "Bug"
_LINKED_BUGS = (
    "SELECT DISTINCT b.key FROM link l JOIN work_item b ON b.source = 'jira' AND b.type = ? "
    "AND b.source_id = CASE WHEN l.from_id = ? THEN l.to_id ELSE l.from_id END "
    "WHERE (l.from_id = ? OR l.to_id = ?) AND l.kind != 'parent' "
    "AND l.from_kind = 'work_item' AND l.to_kind = 'work_item'"
)


def release_of(summary: Optional[str]) -> Optional[str]:
    """`3.41` from `3.41 Regression`, `3.30 regression round 2` or `3.33 regression lite`."""
    match = REGRESSION_TITLE.match(summary or "")
    return match.group(1) if match else None


def version_key(release: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in release.split("."))


def regression_bugs_by_release(
    conn: sqlite3.Connection, project: str = PROJECT, start: date = WINDOW_START
) -> List[Dict[str, Any]]:
    """Bugs linked (any kind but parent) to a release's regression stories. Everything QA links to the
    story was found during regression, even a bug filed before the story existed."""
    releases: Dict[str, Dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT source_id, key, summary, created_at FROM work_item WHERE source = 'jira' AND project = ? AND type = ?",
        (project, REGRESSION_STORY_TYPE),
    ).fetchall():
        release = release_of(row["summary"])
        if release is None:
            continue
        entry = releases.setdefault(release, {"stories": [], "first": row["created_at"] or "", "bugs": set()})
        entry["stories"].append(row["key"])
        entry["first"] = min(entry["first"], row["created_at"] or "")
        sid = row["source_id"]
        entry["bugs"].update(r[0] for r in conn.execute(_LINKED_BUGS, (REGRESSION_BUG_TYPE, sid, sid, sid)))
    kept = sorted((r for r, e in releases.items() if e["first"] >= start.isoformat()), key=version_key)
    return [
        {"release": release, "regression_stories": sorted(releases[release]["stories"], key=key_order),
         "bugs": len(releases[release]["bugs"]), "bug_keys": sorted(releases[release]["bugs"], key=key_order),
         "in_progress": release == kept[-1]}
        for release in kept
    ]
