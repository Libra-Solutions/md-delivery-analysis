from __future__ import annotations

import sqlite3
import statistics
from typing import Any, Dict, List, Optional, Tuple

from delivery_analysis.metrics.people import Scope, actor_key
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window, hours_between, weekly
from delivery_analysis.store.db import remembered

ASSIGNED_NOTE = (
    "Bitbucket does not record when a reviewer was assigned, so assigned reviews are counted "
    "by the pull request's creation date."
)


def _detail_note(conn: sqlite3.Connection, scope: Scope) -> List[str]:
    return list(remembered(conn, ("detail_note", scope.repos), lambda: _count_detail(conn, scope)))


def _count_detail(conn: sqlite3.Connection, scope: Scope) -> List[str]:
    where, params = scope.repo_filter("c.repository_id")
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN d.value = u.value THEN 1 ELSE 0 END) AS done "
        "FROM change_request c "
        "JOIN property u ON u.record_kind = 'change_request' AND u.record_id = c.source_id AND u.name = 'updated_on' "
        "LEFT JOIN property d ON d.record_kind = 'change_request' AND d.record_id = c.source_id "
        "AND d.name = 'detail_updated_on' "
        f"WHERE c.source = 'bitbucket' AND {where}",
        params,
    ).fetchone()
    total, done = row["total"] or 0, row["done"] or 0
    if total and done < total:
        return [f"Review detail covers {done} of {total} pull requests; more fills in with each sync."]
    return []


def _merged(conn: sqlite3.Connection, scope: Scope, window: Window) -> List[sqlite3.Row]:
    where, params = scope.repo_filter("c.repository_id")
    return conn.execute(
        "SELECT c.source_id, c.author_account, c.created_at, c.merged_at, "
        "(SELECT p.value FROM property p WHERE p.record_kind = 'change_request' "
        " AND p.record_id = c.source_id AND p.name = 'times_from') AS times_from "
        "FROM change_request c WHERE c.source = 'bitbucket' AND c.state = 'MERGED' "
        f"AND c.merged_at >= ? AND c.merged_at < ? AND {where}",
        [window.start, window.end] + params,
    ).fetchall()


def prs_merged(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    for row in _merged(conn, scope, window):
        obs.add(actor_key(("bitbucket", row["author_account"])))
    return obs


def time_to_merge(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    approximate = 0
    for row in _merged(conn, scope, window):
        hours = hours_between(row["created_at"], row["merged_at"])
        if hours is None or hours < 0:
            continue
        if row["times_from"] != "activity":
            approximate += 1
        obs.add(actor_key(("bitbucket", row["author_account"])), hours)
    if approximate:
        obs.notes.append(
            f"{approximate} merge times are approximate (taken from the last update) until review detail is fetched."
        )
    return obs


def _review_events(conn: sqlite3.Connection, scope: Scope, window: Optional[Window] = None) -> List[sqlite3.Row]:
    where, params = scope.repo_filter("c.repository_id")
    sql = (
        "SELECT DISTINCT e.actor_account AS account, e.change_request_id AS pr FROM change_event e "
        "JOIN change_request c ON c.source = e.source AND c.source_id = e.change_request_id "
        "WHERE e.source = 'bitbucket' AND e.type IN ('comment', 'approved') AND e.actor_account IS NOT NULL "
        "AND (c.author_account IS NULL OR e.actor_account != c.author_account) "
        f"AND {where}"
    )
    args: List[Any] = list(params)
    if window is not None:
        sql += " AND e.occurred_at >= ? AND e.occurred_at < ?"
        args += [window.start, window.end]
    return conn.execute(sql, args).fetchall()


def reviews_given(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations(notes=_detail_note(conn, scope))
    for row in _review_events(conn, scope, window):
        obs.add(actor_key(("bitbucket", row["account"])))
    return obs


def _assigned(
    conn: sqlite3.Connection, scope: Scope, window: Optional[Window] = None, open_only: bool = False
) -> List[sqlite3.Row]:
    where, params = scope.repo_filter("c.repository_id")
    sql = (
        "SELECT substr(p.name, 10) AS account, p.record_id AS pr, p.value AS state FROM property p "
        "JOIN change_request c ON c.source = 'bitbucket' AND c.source_id = p.record_id "
        "WHERE p.record_kind = 'change_request' AND p.name LIKE 'reviewer:%' "
        f"AND {where}"
    )
    args: List[Any] = list(params)
    if window is not None:
        sql += " AND c.created_at >= ? AND c.created_at < ?"
        args += [window.start, window.end]
    if open_only:
        sql += " AND c.state = 'OPEN'"
    return conn.execute(sql, args).fetchall()


def reviews_assigned(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations(notes=[ASSIGNED_NOTE])
    for row in _assigned(conn, scope, window):
        obs.add(actor_key(("bitbucket", row["account"])))
    return obs


def review_response_rate(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations(notes=[ASSIGNED_NOTE] + _detail_note(conn, scope))
    responded = {(row["account"], row["pr"]) for row in _review_events(conn, scope)}
    for row in _assigned(conn, scope, window):
        done = row["state"] == "approved" or (row["account"], row["pr"]) in responded
        obs.add(actor_key(("bitbucket", row["account"])), 1.0 if done else 0.0)
    return obs


def review_load(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    for row in _assigned(conn, scope, open_only=True):
        if row["state"] == "pending":
            obs.add(actor_key(("bitbucket", row["account"])))
    return obs


def commits(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    where, params = scope.repo_filter("v.repository_id")
    obs = Observations()
    rows = conn.execute(
        "SELECT v.author_account, v.author_email FROM vcs_commit v WHERE v.source = 'bitbucket' "
        "AND v.committed_at >= ? AND v.committed_at < ? "
        "AND NOT EXISTS (SELECT 1 FROM property p WHERE p.record_kind = 'vcs_commit' "
        " AND p.record_id = v.source_id AND p.name = 'is_merge') "
        f"AND {where}",
        [window.start, window.end] + params,
    ).fetchall()
    for row in rows:
        email = (row["author_email"] or "").strip().lower() or None
        obs.add(actor_key(("bitbucket", row["author_account"]), ("email", email)))
    return obs


def work_in_progress(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    where, params = scope.repo_filter("c.repository_id")
    obs = Observations()
    for row in conn.execute(
        f"SELECT c.author_account FROM change_request c WHERE c.source = 'bitbucket' AND c.state = 'OPEN' AND {where}",
        params,
    ):
        obs.add(actor_key(("bitbucket", row["author_account"])))
    return obs


def prs_merged_weekly(conn: sqlite3.Connection, scope: Scope, window: Window) -> Tuple[List[Dict[str, Any]], List[str]]:
    return weekly(window, (row["merged_at"] for row in _merged(conn, scope, window))), []


def _median(values: List[float]) -> Optional[float]:
    return round(float(statistics.median(values)), 2) if values else None


def lead_time_breakdown(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    parts: Dict[str, List[float]] = {
        "Waiting for first review": [],
        "First review to approval": [],
        "Approval to merge": [],
    }
    merged = _merged(conn, scope, window)
    used = 0
    for row in merged:
        if row["times_from"] != "activity":
            continue
        firsts = {
            event["type"]: event["first"]
            for event in conn.execute(
                "SELECT e.type, MIN(e.occurred_at) AS first FROM change_event e "
                "WHERE e.source = 'bitbucket' AND e.change_request_id = ? AND e.type IN ('comment', 'approved') "
                "AND e.actor_account IS NOT NULL AND (? IS NULL OR e.actor_account != ?) GROUP BY e.type",
                (row["source_id"], row["author_account"], row["author_account"]),
            )
        }
        approval = firsts.get("approved")
        review = min(value for value in firsts.values() if value) if firsts else None
        if not review or not approval:
            continue
        spans = (
            hours_between(row["created_at"], review),
            hours_between(review, approval),
            hours_between(approval, row["merged_at"]),
        )
        if any(span is None or span < 0 for span in spans):
            continue
        used += 1
        for name, span in zip(parts, spans):
            parts[name].append(span)
    rows = [{"part": name, "median_hours": _median(values), "count": len(values)} for name, values in parts.items()]
    notes = [f"Based on {used} of {len(merged)} merged pull requests that have an approval and review detail."]
    return rows, notes
