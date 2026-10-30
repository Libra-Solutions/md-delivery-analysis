from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from delivery_analysis.metrics.credit import completed_issues, credit_for, credit_note, qa_shares, scoped
from delivery_analysis.metrics.delivered import DELIVERED_AT_SQL
from delivery_analysis.metrics.people import People, Scope, actor_key
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window, hours_between, weekly

UNASSIGNED_NOTE = "{n} completed issue(s) have no assignee and are not attributed to anyone."
NO_START_NOTE = "{n} completed issue(s) never entered In Progress, so they have no cycle time."
OUTSIDE_NOTE = "{n} completed issue(s) belong to someone outside this team and are not counted."
NO_DATE_NOTE = "{n} done issue(s) have no resolved date and are not counted."
NO_POINTS_NOTE = "{n} completed issue(s) have no story points and are not counted."
NO_QA_NOTE = "{n} completed issue(s) have no QA1 or QA2 set and are not counted."

_DONE_SQL = (
    "SELECT w.source_id, w.assignee_account, w.started_at, " + DELIVERED_AT_SQL + " AS resolved_at, "
    "w.story_points FROM work_item w "
    "JOIN property c ON c.record_kind = 'work_item' AND c.record_id = w.source_id "
    "AND c.name = 'counts_for_impact' AND c.value = '1' "
    "WHERE w.source = 'jira' AND " + DELIVERED_AT_SQL + " >= ? AND " + DELIVERED_AT_SQL + " < ? "
    "ORDER BY " + DELIVERED_AT_SQL
)


_NO_DATE_SQL = (
    "SELECT w.assignee_account FROM work_item w "
    "JOIN property c ON c.record_kind = 'work_item' AND c.record_id = w.source_id "
    "AND c.name = 'counts_for_impact' AND c.value = '1' "
    "WHERE w.source = 'jira' AND w.status_category = 'done' AND " + DELIVERED_AT_SQL + " IS NULL"
)


def _key(account: Optional[str]) -> Optional[str]:
    """Jira and Bitbucket share one account id, so either identity can resolve the person."""
    return actor_key(("jira", account), ("bitbucket", account))


def _in_scope(rows: List[sqlite3.Row], conn: sqlite3.Connection, scope: Scope) -> Tuple[List[sqlite3.Row], int]:
    """Rows kept for the scope, and how many were assigned outside the team.

    Under a team only issues whose assignee resolves to a team member are in scope, so
    unassigned issues and unmapped assignees are not the team's. Without a team all rows are.
    """
    if scope.members is None:
        return list(rows), 0
    people = People(conn)
    kept = []
    outside = 0
    for row in rows:
        key = _key(row["assignee_account"])
        if key is None:
            continue
        if people.resolve(key) in scope.members:
            kept.append(row)
        else:
            outside += 1
    return kept, outside


def _done(conn: sqlite3.Connection, scope: Scope, window: Window) -> Tuple[List[sqlite3.Row], int]:
    return _in_scope(conn.execute(_DONE_SQL, (window.start, window.end)).fetchall(), conn, scope)


def _unresolved(conn: sqlite3.Connection, scope: Scope) -> int:
    return len(_in_scope(conn.execute(_NO_DATE_SQL).fetchall(), conn, scope)[0])


def _notes(obs: Observations, unassigned: int, outside: int, unresolved: int = 0) -> None:
    if unassigned:
        obs.notes.append(UNASSIGNED_NOTE.format(n=unassigned))
    if outside:
        obs.notes.append(OUTSIDE_NOTE.format(n=outside))
    if unresolved:
        obs.notes.append(NO_DATE_NOTE.format(n=unresolved))


def _counts(people: People, scope: Scope, key: str) -> bool:
    """Under a team only members count; with no team everyone does (the registry drops excluded people)."""
    if scope.members is None:
        return True
    return people.resolve(key) in scope.members


def issues_done(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """Each credited author gets the issue once (an issue with two authors adds 1 to each)."""
    credit = credit_for(conn, window)
    people = People(conn)
    obs = Observations()
    unassigned = outside = 0
    for row in credit.issues:
        shares = credit.shares.get(row["source_id"]) or {}
        if not shares:
            if scope.members is None:
                unassigned += 1
            continue
        counted = [key for key in shares if _counts(people, scope, key)]
        if not counted:
            outside += 1
            continue
        for key in counted:
            obs.add(key)
    _notes(obs, unassigned, outside, _unresolved(conn, scope))
    explained = credit_note(credit)
    if explained:
        obs.notes.append(explained)
    return obs


def cycle_time(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    never_started = unassigned = 0
    rows, outside = _done(conn, scope, window)
    for row in rows:
        hours = hours_between(row["started_at"], row["resolved_at"])
        if hours is None or hours < 0:
            never_started += 1
            continue
        key = _key(row["assignee_account"])
        if key is None:
            unassigned += 1
            continue
        obs.add(key, hours)
    if never_started:
        obs.notes.append(NO_START_NOTE.format(n=never_started))
    _notes(obs, unassigned, outside)
    return obs


def story_points_done(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """An issue's points are split by each credited author's share of its linked pull requests."""
    credit = credit_for(conn, window)
    people = People(conn)
    obs = Observations()
    unpointed = unassigned = outside = 0
    for row in credit.issues:
        shares = credit.shares.get(row["source_id"]) or {}
        if not shares and scope.members is not None:
            continue
        counted = {key: share for key, share in shares.items() if _counts(people, scope, key)}
        if shares and not counted:
            outside += 1
            continue
        if row["story_points"] is None:
            unpointed += 1
            continue
        if not shares:
            unassigned += 1
            continue
        for key, share in counted.items():
            obs.add(key, row["story_points"] * share)
    if unpointed:
        obs.notes.append(NO_POINTS_NOTE.format(n=unpointed))
    _notes(obs, unassigned, outside, _unresolved(conn, scope))
    explained = credit_note(credit)
    if explained:
        obs.notes.append(explained)
    return obs


def qa_points_done(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """Story points of delivered issues credited to the Jira QA1/QA2 fields, half each when both differ.
    Separate from story_points_done: an issue counts once for its developers and once for its testers."""
    issues = completed_issues(conn, window)
    testers = qa_shares(conn, [row["source_id"] for row in issues])
    people = People(conn)
    obs = Observations()
    unpointed = untested = outside = 0
    for row in issues:
        shares = testers.get(row["source_id"])
        if not shares:
            untested += 1
            continue
        counted = {key: share for key, share in shares.items() if _counts(people, scope, key)}
        if not counted:
            outside += 1
            continue
        if row["story_points"] is None:
            unpointed += 1
            continue
        for key, share in counted.items():
            obs.add(key, row["story_points"] * share)
    if unpointed:
        obs.notes.append(NO_POINTS_NOTE.format(n=unpointed))
    if untested:
        obs.notes.append(NO_QA_NOTE.format(n=untested))
    _notes(obs, 0, outside)
    return obs


def issues_done_weekly(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Completed issues per local week, each counted once. Under a team an issue counts when a team member
    is credited for it; with no team every completed issue counts, assigned or not."""
    credit = credit_for(conn, window)
    sc = scoped(conn, scope, credit)
    rows = [row for row, _ in sc.items] + (sc.unassigned if scope.members is None else [])
    return weekly(window, [row["resolved_at"] for row in rows]), []
