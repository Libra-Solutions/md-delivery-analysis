# QA Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/qa` page and `/api/qa` endpoint showing QA fail rate and escape defect rate per MD sprint, and regression bug counts per MD release, from 2026-06-01 to today.

**Architecture:** A new pure module `delivery_analysis/metrics/qa.py` reads tables the Jira sync already fills (`work_item`, `work_item_transition`, `link`, `property`) and returns plain dicts keyed by sprint, month or release. `app/api.py` exposes it as JSON and CSV; a static page renders it with the vendored Chart.js. No migration, no sync change, no per-person data.

**Tech Stack:** Python 3, SQLite, FastAPI, pytest, plain JS + Chart.js (vendored).

Spec: `docs/superpowers/specs/2026-10-30-qa-dashboard-design.md`.

## Global Constraints

- Jira project `MD` only; window start `2026-06-01`, end = today (US Eastern, `ctx.today()`).
- Read-only: no writes to the database from these code paths, no Jira calls, no migration.
- No per-person data: no account ids, names or emails in any returned row.
- Static files must not contain `http://` or `https://`; every page carries the full nav; page scripts only use ids present in their page.
- Tests use made-up tickets and `*.example` people only.
- Do not stage or commit the pre-existing uncommitted changes on `QA-Metrics` (`.env.example`, `README.md` hunks, `person.js`, `clone.py`, `jira/connector.py`, `catalog.py`, `credit.py`, `metrics/jira.py`, `tests/test_code_clone.py`, `tests/test_jira_developer_scope.py`, `tests/test_metrics_bitbucket.py`, `tests/test_metrics_qa_points.py`). Stage files by explicit path only.
- Run tests with `uv run pytest` (or `.venv/Scripts/python.exe -m pytest` when `uv` is not on PATH).

---

### Task 1: Sprint parsing and QA fail rate

**Files:**
- Create: `delivery_analysis/metrics/qa.py`
- Create: `tests/qa_seed.py`
- Test: `tests/test_metrics_qa.py`

**Interfaces:**
- Produces: constants `PROJECT`, `WINDOW_START`, `SPRINT_FIELD`; `last_sprint(value: Optional[str]) -> Optional[dict]`;
  `list_sprints(conn, project, start: date, today: date) -> List[dict]` (keys `sprint_id, name, start, end, in_progress`);
  `qa_fail_by_sprint(conn, sprints, project, start) -> {"rows": [...], "unsprinted_tested": int}` (row keys
  `sprint_id, tested, failed, fail_rate, failed_keys, sub_bugs_on_tested, sub_bugs_per_story`); helpers `ratio`, `key_order`.
- Produces (tests): `tests/qa_seed.py` with `S0, S1, S2, S3, C3S`, `ticket()`, `move()`, `link()`, `qa_pass()`.

- [ ] **Step 1: Write the seed helpers** — `tests/qa_seed.py`:

```python
"""Made-up MD tickets for QA dashboard tests. Sprints S1-S3 run June to mid July 2026; S0 starts
before the window and C3S belongs to another board."""
import itertools
import json

from metrics_seed import prop, put

S0 = {"id": 10, "name": "MD Sprint 0", "startDate": "2026-05-20T00:00:00Z", "endDate": "2026-06-03T00:00:00Z", "state": "closed", "boardId": 9}
S1 = {"id": 11, "name": "MD Sprint 1", "startDate": "2026-06-03T00:00:00Z", "endDate": "2026-06-17T00:00:00Z", "state": "closed", "boardId": 9}
S2 = {"id": 12, "name": "MD Sprint 2", "startDate": "2026-06-17T00:00:00Z", "endDate": "2026-07-01T00:00:00Z", "state": "closed", "boardId": 9}
S3 = {"id": 13, "name": "MD Sprint 3", "startDate": "2026-07-01T00:00:00Z", "endDate": "2026-07-15T00:00:00Z", "state": "active", "boardId": 9}
C3S = {"id": 50, "name": "C3 Sprint 9", "startDate": "2026-06-20T00:00:00Z", "endDate": "2026-07-04T00:00:00Z", "state": "closed", "boardId": 7}
SPRINT_FIELD = "sprint_10006"

_moves = itertools.count(1)


def ticket(conn, n, type_, created, sprints=None, summary="Work", project="MD", assignee="acc-tess"):
    sid = f"{project.lower()}{n}"
    put(conn, "work_item", source="jira", source_id=sid, project=project, key=f"{project}-{n}", type=type_,
        summary=summary, status="To Do", status_category="todo", created_at=created, assignee_account=assignee)
    if sprints is not None:
        prop(conn, "work_item", sid, SPRINT_FIELD, json.dumps(sprints))
    return sid


def move(conn, sid, frm, to, at):
    put(conn, "work_item_transition", source="jira", source_id=f"{sid}:{next(_moves)}", work_item_id=sid,
        from_status=frm, to_status=to, occurred_at=at, actor_account="acc-tess")


def link(conn, frm, to, kind):
    put(conn, "link", source="jira", source_id=f"{kind}:{frm}:{to}", from_kind="work_item", from_id=frm,
        to_kind="work_item", to_id=to, kind=kind, found_by="jira")


def qa_pass(conn, sid, day, bounce_from=None):
    """Ready for QA -> In QA on `day`; with `bounce_from`, a later move from that status back to In Progress."""
    move(conn, sid, "Code Review", "Ready for QA", f"{day}T10:00:00Z")
    move(conn, sid, "Ready for QA", "In QA", f"{day}T11:00:00Z")
    if bounce_from == "In QA":
        move(conn, sid, "In QA", "In Progress", f"{day}T12:00:00Z")
    elif bounce_from == "Ready for QA":
        move(conn, sid, "Ready for QA", "In Progress", f"{day}T09:00:00Z")
    else:
        move(conn, sid, "In QA", "Dev Done", f"{day}T12:00:00Z")
```

- [ ] **Step 2: Write the failing tests** — `tests/test_metrics_qa.py`:

```python
import json
from datetime import date

from qa_seed import C3S, S0, S1, S2, S3, link, move, qa_pass, ticket
from delivery_analysis.metrics import qa

START = date(2026, 6, 1)
TODAY = date(2026, 7, 20)


def test_last_sprint_takes_the_latest_md_sprint_and_ignores_other_boards():
    assert qa.last_sprint(json.dumps([S1, C3S, S2])) == S2
    assert qa.last_sprint(json.dumps([C3S])) is None
    assert qa.last_sprint("not json") is None
    assert qa.last_sprint(None) is None
    assert qa.last_sprint(json.dumps([{"id": 99, "name": "MD Sprint 9"}])) is None  # future: no start date


def test_list_sprints_keeps_md_sprints_starting_in_the_window(conn):
    ticket(conn, 1, "Story", "2026-05-25T00:00:00Z", [S0, S1])
    ticket(conn, 2, "Story", "2026-06-20T00:00:00Z", [S2, C3S])
    ticket(conn, 3, "Story", "2026-07-02T00:00:00Z", [S3])
    sprints = qa.list_sprints(conn, "MD", START, TODAY)
    assert [s["name"] for s in sprints] == ["MD Sprint 1", "MD Sprint 2", "MD Sprint 3"]
    assert [s["in_progress"] for s in sprints] == [False, False, True]
    assert sprints[0] == {"sprint_id": 11, "name": "MD Sprint 1", "start": S1["startDate"], "end": S1["endDate"], "in_progress": False}


def test_qa_fail_rate_counts_bounces_from_qa_back_to_development(conn):
    passed = ticket(conn, 1, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, passed, "2026-06-05")
    failed = ticket(conn, 2, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, failed, "2026-06-06", bounce_from="In QA")
    carried = ticket(conn, 3, "Story", "2026-06-03T00:00:00Z", [S1, S2])  # counts in its last sprint
    qa_pass(conn, carried, "2026-06-20", bounce_from="Ready for QA")
    untested = ticket(conn, 4, "Story", "2026-06-03T00:00:00Z", [S1])
    move(conn, untested, "To Do", "In Progress", "2026-06-05T00:00:00Z")
    loose = ticket(conn, 5, "Story", "2026-06-03T00:00:00Z")
    qa_pass(conn, loose, "2026-06-10")
    bug = ticket(conn, 6, "Bug", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, bug, "2026-06-07", bounce_from="In QA")
    sub = ticket(conn, 7, "Sub-bug", "2026-06-06T00:00:00Z", [S1])
    link(conn, sub, failed, "parent")
    ticket(conn, 8, "Story", "2026-07-02T00:00:00Z", [S3])

    sprints = qa.list_sprints(conn, "MD", START, TODAY)
    result = qa.qa_fail_by_sprint(conn, sprints, "MD", START)
    rows = {r["sprint_id"]: r for r in result["rows"]}
    assert rows[11] == {"sprint_id": 11, "tested": 2, "failed": 1, "fail_rate": 0.5, "failed_keys": ["MD-2"],
                        "sub_bugs_on_tested": 1, "sub_bugs_per_story": 0.5}
    assert rows[12]["tested"] == 1 and rows[12]["failed"] == 1 and rows[12]["fail_rate"] == 1.0
    assert rows[13]["tested"] == 0 and rows[13]["fail_rate"] is None and rows[13]["sub_bugs_per_story"] is None
    assert result["unsprinted_tested"] == 1


def test_key_order_sorts_by_ticket_number():
    assert sorted(["MD-100", "MD-99", "MD-7"], key=qa.key_order) == ["MD-7", "MD-99", "MD-100"]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_metrics_qa.py -v`
Expected: FAIL — `ImportError: cannot import name 'qa'`.

- [ ] **Step 4: Implement** — `delivery_analysis/metrics/qa.py`:

```python
"""QA status numbers for one Jira project, by sprint, month and release.

Read-only over what the Jira sync stores. Rows are keyed by sprint, month or release and never carry
people: ranking testers by bugs found would push them to file fewer bugs.
"""
from __future__ import annotations

import json
import re
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
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_metrics_qa.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add delivery_analysis/metrics/qa.py tests/qa_seed.py tests/test_metrics_qa.py
git commit -m "Add QA fail rate by MD sprint"
```

---

### Task 2: Escape defect rate by sprint and month

**Files:**
- Modify: `delivery_analysis/metrics/qa.py` (append)
- Test: `tests/test_metrics_qa.py` (append)

**Interfaces:**
- Consumes: `list_sprints`, `ratio`, `key_order` from Task 1.
- Produces: `escape_rate_by_sprint(conn, sprints, project) -> List[dict]` (keys `sprint_id, defects, bugs, sub_bugs, found, escape_rate, defect_keys`);
  `escape_rate_by_month(conn, project, start, today, tz) -> List[dict]` (same keys with `month` "YYYY-MM" in place of `sprint_id`).

- [ ] **Step 1: Write the failing tests** (append):

```python
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")


def _escape_seed(conn):
    ticket(conn, 1, "Defect", "2026-06-05T00:00:00Z", [S1])
    ticket(conn, 2, "Bug", "2026-06-06T00:00:00Z", [S1])
    ticket(conn, 3, "Sub-bug", "2026-06-07T00:00:00Z", [S1])
    ticket(conn, 4, "Story", "2026-06-05T00:00:00Z", [S1])
    ticket(conn, 5, "Bug", "2026-06-20T00:00:00Z", [S2])
    ticket(conn, 6, "Defect", "2026-07-01T02:00:00Z", [S3])  # 1 July UTC is still 30 June in New York
    ticket(conn, 7, "Defect", "2026-06-05T00:00:00Z", [C3S], project="C3")


def test_escape_rate_by_sprint_uses_creation_inside_the_sprint_dates(conn):
    _escape_seed(conn)
    sprints = qa.list_sprints(conn, "MD", START, TODAY)
    rows = {r["sprint_id"]: r for r in qa.escape_rate_by_sprint(conn, sprints, "MD")}
    assert rows[11] == {"sprint_id": 11, "defects": 1, "bugs": 1, "sub_bugs": 1, "found": 3,
                        "escape_rate": 1 / 3, "defect_keys": ["MD-1"]}
    assert rows[12]["found"] == 1 and rows[12]["escape_rate"] == 0.0
    assert rows[13]["defects"] == 1 and rows[13]["escape_rate"] == 1.0


def test_escape_rate_by_month_uses_report_time_zone(conn):
    _escape_seed(conn)
    rows = qa.escape_rate_by_month(conn, "MD", START, TODAY, TZ)
    assert [r["month"] for r in rows] == ["2026-06", "2026-07"]
    assert rows[0]["defects"] == 2 and rows[0]["found"] == 5 and rows[0]["defect_keys"] == ["MD-1", "MD-6"]
    assert rows[1]["found"] == 0 and rows[1]["escape_rate"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_metrics_qa.py -v`
Expected: 2 new tests FAIL with `AttributeError: module ... has no attribute 'escape_rate_by_sprint'`.

- [ ] **Step 3: Implement** (append to `qa.py`; add `from datetime import datetime, timezone, tzinfo` to the imports):

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_metrics_qa.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add delivery_analysis/metrics/qa.py tests/test_metrics_qa.py
git commit -m "Add escape defect rate by MD sprint and month"
```

---

### Task 3: Regression bugs per release

**Files:**
- Modify: `delivery_analysis/metrics/qa.py` (append)
- Test: `tests/test_metrics_qa.py` (append)

**Interfaces:**
- Consumes: `key_order` from Task 1.
- Produces: `release_of(summary) -> Optional[str]`, `version_key(release) -> Tuple[int, ...]`,
  `regression_bugs_by_release(conn, project, start) -> List[dict]` (keys `release, regression_stories, bugs, bug_keys, in_progress`).

- [ ] **Step 1: Write the failing tests** (append):

```python
def test_release_of_reads_the_version_from_regression_story_titles():
    assert qa.release_of("3.41 Regression") == "3.41"
    assert qa.release_of("  3.33 regression lite") == "3.33"
    assert qa.release_of("3.30 regression round 2") == "3.30"
    assert qa.release_of("MoveDocs UI Automation - Close Manual Regression Gap") is None
    assert qa.release_of("3.40 regressions found") is None
    assert qa.release_of(None) is None
    assert sorted(["3.10", "3.9"], key=qa.version_key) == ["3.9", "3.10"]


def test_regression_bugs_counts_every_bug_linked_to_the_release_stories(conn):
    r0 = ticket(conn, 1, "Story", "2026-05-22T00:00:00Z", summary="3.35 regression")
    r1 = ticket(conn, 2, "Story", "2026-06-10T00:00:00Z", summary="3.36 regression")
    r2 = ticket(conn, 3, "Story", "2026-06-20T00:00:00Z", summary="3.36 Regression round 2")
    r3 = ticket(conn, 4, "Story", "2026-07-01T00:00:00Z", summary="3.37 REGRESSION lite")
    ticket(conn, 5, "Story", "2026-06-10T00:00:00Z", summary="Add regression coverage")
    ticket(conn, 6, "Bug", "2026-06-11T00:00:00Z", summary="3.36 regression in login")
    b1 = ticket(conn, 7, "Bug", "2026-06-11T00:00:00Z")
    b2 = ticket(conn, 8, "Bug", "2026-06-21T00:00:00Z")
    b3 = ticket(conn, 9, "Bug", "2026-05-01T00:00:00Z")  # found before the story existed: still counts
    b4 = ticket(conn, 10, "Bug", "2026-06-12T00:00:00Z")
    story = ticket(conn, 11, "Story", "2026-07-02T00:00:00Z")
    old = ticket(conn, 12, "Bug", "2026-05-23T00:00:00Z")
    link(conn, r1, b1, "Block")
    link(conn, r2, b1, "Relates")       # same bug twice in one release counts once
    link(conn, b2, r2, "Relates")       # inward direction
    link(conn, r3, b3, "Blocks")
    link(conn, r3, story, "Relates")    # not a bug
    link(conn, r3, "99999", "Test")     # not synced
    link(conn, b4, r1, "parent")        # parent links are not regression links
    link(conn, r0, old, "Block")        # 3.35 regression started before the window
    rows = qa.regression_bugs_by_release(conn, "MD", START)
    assert rows == [
        {"release": "3.36", "regression_stories": ["MD-2", "MD-3"], "bugs": 2, "bug_keys": ["MD-7", "MD-8"],
         "in_progress": False},
        {"release": "3.37", "regression_stories": ["MD-4"], "bugs": 1, "bug_keys": ["MD-9"], "in_progress": True},
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_metrics_qa.py -v`
Expected: 2 new tests FAIL with `AttributeError: ... 'release_of'`.

- [ ] **Step 3: Implement** (append to `qa.py`):

```python
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
    ):
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_metrics_qa.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add delivery_analysis/metrics/qa.py tests/test_metrics_qa.py
git commit -m "Count regression bugs per MD release"
```

---

### Task 4: Dashboard bundle, CSV and API routes

**Files:**
- Modify: `delivery_analysis/metrics/qa.py` (append `qa_dashboard`)
- Modify: `delivery_analysis/metrics/export.py` (append `qa_csv`)
- Modify: `delivery_analysis/app/api.py` (imports; two routes inside `build_router`, before `@router.get("/settings")`)
- Test: `tests/test_metrics_qa.py` (append), `tests/test_app_api_qa.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: `qa_dashboard(conn, today, tz, project=PROJECT, start=WINDOW_START) -> dict` with keys
  `project, window{start,end}, sprints[], months[], releases[], unsprinted_tested, headline{sprint, release}`;
  each sprint row = `list_sprints` row + QA fail keys + escape keys. `qa_csv(data) -> str`.
  `GET /api/qa`, `GET /api/qa/export.csv`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/qa_seed.py`:

```python
def seed_dashboard(conn):
    """A small MD history: S1 and S2 closed, S3 active; releases 3.36 (done) and 3.37 (in progress)."""
    a = ticket(conn, 1, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, a, "2026-06-05")
    b = ticket(conn, 2, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, b, "2026-06-06", bounce_from="In QA")
    ticket(conn, 3, "Defect", "2026-06-05T00:00:00Z", [S1])
    bug = ticket(conn, 4, "Bug", "2026-06-06T00:00:00Z", [S1])
    c = ticket(conn, 5, "Story", "2026-06-18T00:00:00Z", [S2])
    qa_pass(conn, c, "2026-06-20", bounce_from="In QA")
    r1 = ticket(conn, 6, "Story", "2026-06-10T00:00:00Z", summary="3.36 regression")
    link(conn, r1, bug, "Block")
    r2 = ticket(conn, 7, "Story", "2026-07-01T00:00:00Z", summary="3.37 regression")
    late = ticket(conn, 8, "Bug", "2026-07-02T00:00:00Z", [S3])
    link(conn, r2, late, "Block")
```

Append to `tests/test_metrics_qa.py`:

```python
from qa_seed import seed_dashboard


def test_dashboard_merges_sprint_rows_and_picks_closed_headlines(conn):
    seed_dashboard(conn)
    data = qa.qa_dashboard(conn, TODAY, TZ)
    assert data["project"] == "MD" and data["window"] == {"start": "2026-06-01", "end": "2026-07-20"}
    first = data["sprints"][0]
    assert first["name"] == "MD Sprint 1" and first["fail_rate"] == 0.5 and first["escape_rate"] == 0.5
    assert data["headline"]["sprint"]["name"] == "MD Sprint 2"
    assert data["headline"]["release"]["release"] == "3.36"
    assert [m["month"] for m in data["months"]] == ["2026-06", "2026-07"]
    assert "acc-tess" not in json.dumps(data)
```

Create `tests/test_app_api_qa.py`:

```python
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from qa_seed import seed_dashboard
from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.server import create_app
from delivery_analysis.settings import Settings
from delivery_analysis.store import db

CLOCK = lambda: datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc)  # noqa: E731


def make(tmp_path):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    seed_dashboard(conn)
    conn.close()
    app = create_app(path, settings=Settings(db_path=path), environ={}, worker=RefreshWorker(lambda s, f: "ok"),
                     clock=CLOCK, port=8000)
    return TestClient(app, base_url="http://127.0.0.1")


def test_qa_api_returns_sprints_months_releases_and_no_people(tmp_path):
    client = make(tmp_path)
    response = client.get("/api/qa")
    assert response.status_code == 200
    data = response.json()
    assert [s["name"] for s in data["sprints"]] == ["MD Sprint 1", "MD Sprint 2", "MD Sprint 3"]
    assert data["headline"]["sprint"]["failed_keys"] == ["MD-5"]
    assert [r["release"] for r in data["releases"]] == ["3.36", "3.37"]
    assert "acc-tess" not in response.text


def test_qa_csv_has_one_section_per_grain(tmp_path):
    client = make(tmp_path)
    response = client.get("/api/qa/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="qa-md.csv"' in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")
    for heading in ("Sprints", "Months", "Regression bugs by release"):
        assert heading + "\r\n" in text
    assert "MD Sprint 1," in text and "3.36," in text
    assert "acc-tess" not in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_metrics_qa.py tests/test_app_api_qa.py -v`
Expected: FAIL — `qa_dashboard` missing; `/api/qa` returns 404.

- [ ] **Step 3: Implement `qa_dashboard`** (append to `qa.py`):

```python
def qa_dashboard(
    conn: sqlite3.Connection, today: date, tz: tzinfo, project: str = PROJECT, start: date = WINDOW_START
) -> Dict[str, Any]:
    sprints = list_sprints(conn, project, start, today)
    fail = qa_fail_by_sprint(conn, sprints, project, start)
    escape = escape_rate_by_sprint(conn, sprints, project)
    rows = [{**sprint, **f, **e} for sprint, f, e in zip(sprints, fail["rows"], escape)]
    releases = regression_bugs_by_release(conn, project, start)
    closed = [r for r in rows if not r["in_progress"]]
    finished = [r for r in releases if not r["in_progress"]]
    return {
        "project": project,
        "window": {"start": start.isoformat(), "end": today.isoformat()},
        "sprints": rows,
        "months": escape_rate_by_month(conn, project, start, today, tz),
        "releases": releases,
        "unsprinted_tested": fail["unsprinted_tested"],
        "headline": {"sprint": closed[-1] if closed else None, "release": finished[-1] if finished else None},
    }
```

- [ ] **Step 4: Implement `qa_csv`** (append to `delivery_analysis/metrics/export.py`; add `Dict` to its `typing` import):

```python
def qa_csv(data: Dict[str, Any]) -> str:
    """The QA dashboard as one CSV: a section per grain, ticket keys space-separated."""
    keys = lambda values: " ".join(values)  # noqa: E731
    rows: List[List[Any]] = [["Sprints"], [
        "sprint", "start", "end", "in_progress", "stories_tested", "stories_failed_qa", "qa_fail_rate",
        "sub_bugs_on_tested", "sub_bugs_per_story", "defects", "bugs", "sub_bugs", "escape_defect_rate",
        "failed_keys", "defect_keys",
    ]]
    for s in data["sprints"]:
        rows.append([
            s["name"], s["start"], s["end"], s["in_progress"], s["tested"], s["failed"], s["fail_rate"],
            s["sub_bugs_on_tested"], s["sub_bugs_per_story"], s["defects"], s["bugs"], s["sub_bugs"],
            s["escape_rate"], keys(s["failed_keys"]), keys(s["defect_keys"]),
        ])
    rows += [[], ["Months"], ["month", "defects", "bugs", "sub_bugs", "escape_defect_rate", "defect_keys"]]
    for m in data["months"]:
        rows.append([m["month"], m["defects"], m["bugs"], m["sub_bugs"], m["escape_rate"], keys(m["defect_keys"])])
    rows += [[], ["Regression bugs by release"], ["release", "in_progress", "regression_bugs", "regression_stories", "bug_keys"]]
    for r in data["releases"]:
        rows.append([r["release"], r["in_progress"], r["bugs"], keys(r["regression_stories"]), keys(r["bug_keys"])])
    return _write(rows)
```

- [ ] **Step 5: Add the routes.** In `delivery_analysis/app/api.py`, change the export import to
`from delivery_analysis.metrics.export import person_csv, qa_csv`, add `from delivery_analysis.metrics.qa import qa_dashboard`, and insert before `@router.get("/settings")`:

```python
    @router.get("/qa")
    def qa() -> Dict[str, Any]:
        with _db(ctx) as conn:
            return qa_dashboard(conn, ctx.today(), ctx.settings.report_tz)

    @router.get("/qa/export.csv")
    def qa_export() -> Response:
        with _db(ctx) as conn:
            body = qa_csv(qa_dashboard(conn, ctx.today(), ctx.settings.report_tz))
        return Response(
            content=b"\xef\xbb\xbf" + body.encode("utf-8"), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="qa-md.csv"'},
        )
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/test_metrics_qa.py tests/test_app_api_qa.py tests/test_metrics_export.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add delivery_analysis/metrics/qa.py delivery_analysis/metrics/export.py delivery_analysis/app/api.py tests/qa_seed.py tests/test_metrics_qa.py tests/test_app_api_qa.py
git commit -m "Serve the QA dashboard as JSON and CSV"
```

---

### Task 5: QA page and nav

**Files:**
- Create: `delivery_analysis/app/static/qa.html`, `delivery_analysis/app/static/pages/qa.js`
- Modify: every other `delivery_analysis/app/static/*.html` (nav link), `delivery_analysis/app/server.py` (`PAGES`)
- Modify: `tests/test_static_assets.py` (`NAV_LABELS`, `API_ROOTS`, `NAV`), `tests/test_app_server.py` (page count)

**Interfaces:**
- Consumes: `GET /api/qa` JSON from Task 4.

- [ ] **Step 1: Update the tests first.** In `tests/test_static_assets.py`: add `"QA"` to `NAV_LABELS`, add `"qa"` to `API_ROOTS`, and change `NAV` to

```python
NAV = (
    '<a href="/">Dashboard</a>\n    <a href="/person">People</a>\n    <a href="/rankings">Rankings</a>\n'
    '    <a href="/qa">QA</a>\n'
    '    <a href="/ask">Ask</a>\n    <h2 class="nav-group">Set up</h2>\n    <a href="/selection">Selection</a>\n'
    '    <a href="/teams">Teams</a>\n    <a href="/sources">Sources</a>\n    <a href="/settings">Settings</a>'
)
```

Append:

```python
def test_the_qa_page_loads_charts_and_shows_no_people():
    html, script = read("qa.html"), read("pages", "qa.js")
    assert "<title>QA · Delivery Analytics</title>" in html and "<h2>QA</h2>" in html
    assert html.index("/static/vendor/chart.umd.js") < html.index("/static/charts.js") < html.index("/static/pages/qa.js")
    assert '"/api/qa"' in script and "person" not in script
```

In `tests/test_app_server.py` change `assert len(PAGES) == 9` to `assert len(PAGES) == 10`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_static_assets.py tests/test_app_server.py -q`
Expected: FAIL (nav missing QA; `qa.html` missing; 9 pages).

- [ ] **Step 3: Add the nav link to every existing page** (keeps CRLF):

```bash
.venv/Scripts/python.exe - <<'EOF'
from pathlib import Path
for page in Path("delivery_analysis/app/static").glob("*.html"):
    data = page.read_bytes()
    old = b'<a href="/rankings">Rankings</a>\r\n'
    assert data.count(old) == 1, page
    page.write_bytes(data.replace(old, old + b'    <a href="/qa">QA</a>\r\n'))
EOF
```

- [ ] **Step 4: Register the page** in `delivery_analysis/app/server.py` `PAGES`: add `"/qa": "qa.html",` after the `"/rankings"` entry.

- [ ] **Step 5: Create `delivery_analysis/app/static/qa.html`:**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QA · Delivery Analytics</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <nav id="nav">
    <h1>Delivery Analytics</h1>
    <a href="/">Dashboard</a>
    <a href="/person">People</a>
    <a href="/rankings">Rankings</a>
    <a href="/qa">QA</a>
    <a href="/ask">Ask</a>
    <h2 class="nav-group">Set up</h2>
    <a href="/selection">Selection</a>
    <a href="/teams">Teams</a>
    <a href="/sources">Sources</a>
    <a href="/settings">Settings</a>
  </nav>
  <div class="page">
    <header id="header"></header>
    <main id="content">
      <h2>QA</h2>
      <p id="qa-scope" class="note"></p>
      <div id="qa-headline" class="stats"></div>
      <p class="note"><a href="/api/qa/export.csv">Download CSV</a></p>
      <div id="qa-charts" class="cards"></div>
      <div id="qa-releases" class="cards"></div>
      <div id="qa-detail"></div>
    </main>
  </div>
  <script src="/static/vendor/chart.umd.js"></script>
  <script src="/static/app.js"></script>
  <script src="/static/charts.js"></script>
  <script src="/static/pages/qa.js"></script>
</body>
</html>
```

- [ ] **Step 6: Create `delivery_analysis/app/static/pages/qa.js`:**

```js
(function () {
  "use strict";
  const DA = window.DA;

  function pct(value) { return DA.fmt(value, "ratio"); }
  function asPct(value) { return value === null || value === undefined ? null : Math.round(value * 1000) / 10; }

  function showKeys(title, keys) {
    const box = document.getElementById("qa-detail");
    box.textContent = "";
    const body = DA.card(box, title, keys.length + " tickets");
    body.appendChild(DA.el("p", { text: keys.join(", ") }));
    box.scrollIntoView({ behavior: "smooth" });
  }

  function keysLink(text, title, keys) {
    if (!keys || !keys.length) { return DA.el("span", { text: text }); }
    return DA.el("a", { href: "#qa-detail", text: text, onclick: function (event) { event.preventDefault(); showKeys(title, keys); } });
  }

  function table(body, headers, rows) {
    const head = DA.el("tr", {}, headers.map(function (h, i) { return DA.el("th", { class: i ? "num" : "", text: h }); }));
    const lines = rows.map(function (cells) {
      return DA.el("tr", {}, cells.map(function (cell, i) {
        return DA.el("td", { class: i ? "num" : "" }, [typeof cell === "string" ? DA.el("span", { text: cell }) : cell]);
      }));
    });
    body.appendChild(DA.el("table", {}, [DA.el("thead", {}, [head]), DA.el("tbody", {}, lines)]));
  }

  function tile(box, value, label) {
    box.appendChild(DA.el("div", { class: "stat" }, [DA.el("strong", { text: value }), DA.el("span", { text: label })]));
  }

  function headline(data) {
    const box = document.getElementById("qa-headline");
    box.textContent = "";
    const s = data.headline.sprint;
    const r = data.headline.release;
    tile(box, s ? pct(s.fail_rate) : "–", "QA fail rate" + (s ? " · " + s.name : ""));
    tile(box, s ? pct(s.escape_rate) : "–", "Escape defect rate" + (s ? " · " + s.name : ""));
    tile(box, r ? String(r.bugs) : "–", "Regression bugs" + (r ? " · release " + r.release : ""));
  }

  function sprintCharts(data) {
    const box = document.getElementById("qa-charts");
    box.textContent = "";
    const labels = data.sprints.map(function (s) { return s.name + (s.in_progress ? " (in progress)" : ""); });

    const fail = DA.card(box, "QA fail rate by sprint", "Stories that reached In QA and were sent back to development");
    DA.charts.series(DA.canvas(fail), labels, [{ label: "QA fail rate %", data: data.sprints.map(function (s) { return asPct(s.fail_rate); }) }], { type: "line" });
    table(fail, ["Sprint", "Tested", "Failed QA", "Fail rate", "Sub-bugs per Story"], data.sprints.map(function (s, i) {
      return [labels[i], String(s.tested), keysLink(String(s.failed), s.name + " · failed QA", s.failed_keys), pct(s.fail_rate), DA.fmt(s.sub_bugs_per_story)];
    }));

    const escape = DA.card(box, "Escape defect rate by sprint", "Defects ÷ (Defects + Bugs + Sub-bugs) created during the sprint");
    DA.charts.series(DA.canvas(escape), labels, [{ label: "Escape defect rate %", data: data.sprints.map(function (s) { return asPct(s.escape_rate); }) }], { type: "line" });
    table(escape, ["Sprint", "Defects", "Bugs", "Sub-bugs", "Escape rate"], data.sprints.map(function (s, i) {
      return [labels[i], keysLink(String(s.defects), s.name + " · Defects", s.defect_keys), String(s.bugs), String(s.sub_bugs), pct(s.escape_rate)];
    }));

    const month = DA.card(box, "Escape defect rate by month", "Same rate by calendar month (US Eastern)");
    const months = data.months.map(function (m) { return m.month; });
    DA.charts.series(DA.canvas(month), months, [{ label: "Escape defect rate %", data: data.months.map(function (m) { return asPct(m.escape_rate); }) }]);
    table(month, ["Month", "Defects", "Bugs", "Sub-bugs", "Escape rate"], data.months.map(function (m) {
      return [m.month, keysLink(String(m.defects), m.month + " · Defects", m.defect_keys), String(m.bugs), String(m.sub_bugs), pct(m.escape_rate)];
    }));
  }

  function releases(data) {
    const box = document.getElementById("qa-releases");
    box.textContent = "";
    const body = DA.card(box, "Regression bugs by release", "Bugs linked to the release's X.XX Regression stories");
    const labels = data.releases.map(function (r) { return r.release + (r.in_progress ? " (in progress)" : ""); });
    DA.charts.series(DA.canvas(body), labels, [{ label: "Regression bugs", data: data.releases.map(function (r) { return r.bugs; }) }]);
    table(body, ["Release", "Regression bugs", "Regression stories"], data.releases.map(function (r, i) {
      return [labels[i], keysLink(String(r.bugs), "Release " + r.release + " · regression bugs", r.bug_keys), r.regression_stories.join(", ")];
    }));
  }

  function render(data) {
    const scope = "Jira project " + data.project + ", " + data.window.start + " to " + data.window.end +
      ". Team, sprint and release figures only. The team and window pickers above do not apply here.";
    const loose = data.unsprinted_tested ? " " + data.unsprinted_tested + " tested Stories had no sprint and are left out." : "";
    DA.message(document.getElementById("qa-scope"), scope + loose);
    headline(data);
    sprintCharts(data);
    releases(data);
  }

  DA.page(function () {
    DA.api("/api/qa").then(render).catch(function (error) {
      DA.message(document.getElementById("qa-charts"), "Could not load QA numbers: " + error.message, "error");
    });
  });
})();
```

- [ ] **Step 7: Run to verify pass**

Run: `uv run pytest tests/test_static_assets.py tests/test_app_server.py tests/test_app_api.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add delivery_analysis/app/static/*.html delivery_analysis/app/static/pages/qa.js delivery_analysis/app/server.py tests/test_static_assets.py tests/test_app_server.py
git commit -m "Add the QA page and link it from the nav"
```

---

### Task 6: README, full suite, real-data check

**Files:**
- Modify: `README.md` (new `## QA dashboard` section before `## Quick start`)

- [ ] **Step 1: Write the README section**:

```markdown
## QA dashboard

The **QA** page (`/qa`) shows three numbers for Jira project MD from 2026-06-01 to today, by sprint,
month and release only — never by person.

| Number | How it is counted |
|---|---|
| QA fail rate (per sprint) | Stories that reached In QA, and the share moved from Ready for QA or In QA back to In Progress, To Do or Code Review. Also Sub-bugs per tested Story. |
| Escape defect rate (per sprint and month) | Defects ÷ (Defects + Bugs + Sub-bugs) created during the sprint or month. |
| Regression bugs (per release) | Bugs linked by any link type to the release's `X.XX Regression` stories (rounds and "lite" included). |

A ticket counts in the last sprint in its Sprint field. Status names, the sprint prefix and the title
pattern are constants at the top of `delivery_analysis/metrics/qa.py`. `/api/qa/export.csv` downloads the
same tables.
```

- [ ] **Step 2: Commit only that hunk** (README has unrelated uncommitted edits): build the patch of just this section against `HEAD` and apply it to the index with `git apply --cached`, then `git commit -m "Document the QA dashboard"`. Check `git diff --cached` shows only the new section first.

- [ ] **Step 3: Full suite**

Run: `uv run pytest -q`
Expected: all pass (note any failures that already existed before this work).

- [ ] **Step 4: Real-data check (read-only)** — call `qa_dashboard` against a read-only connection to `~/github-analysis-results/delivery.sqlite` and confirm sprint names are `MD Sprint 76+`, fail rates are in the 5-25% range seen during discovery, and releases run 3.36 to 3.41 with 3.40 ≈ 33 bugs.

- [ ] **Step 5: Run the app and load `/qa`** (`run` skill) to check the page renders.
