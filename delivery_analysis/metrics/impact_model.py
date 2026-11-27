"""Per-person impact = delivery + participation, in story points, read from the stored impact build.

`impact_build.rebuild_impact` values each completed issue by its story points and the code it touched, gives
delivery to the pull request owners (less a penalty per fixed review comment) and participation to reviewers
whose comments were fixed. Reviewing counts (`prs_reviewed`, `review_value`) come straight from comments and
approvals on other people's pull requests.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional

from delivery_analysis.store.db import all_rows, remembered
from delivery_analysis.metrics import bitbucket as bb
from delivery_analysis.metrics import tokens as tk
from delivery_analysis.metrics.credit import actor_for, completed_issues
from delivery_analysis.metrics.people import People, Scope, actor_key
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window, hours_between

Shares = Dict[str, Dict[str, Dict[str, float]]]

OUTSIDE_NOTE = "{points:g} impact point(s) went to people outside this team and are not counted."

_MERGES_SQL = (
    "SELECT l.to_id AS issue_id, c.merged_at FROM link l JOIN change_request c ON c.source = 'bitbucket' "
    "AND c.source_id = l.from_id WHERE l.kind = 'implements' AND l.from_kind = 'change_request' "
    "AND l.to_kind = 'work_item' AND c.state = 'MERGED' AND c.merged_at IS NOT NULL"
)


def _cohort(conn: sqlite3.Connection, window: Window) -> List[sqlite3.Row]:
    return [row for row in completed_issues(conn, window) if row["story_points"] is not None]


def impact_shares(conn: sqlite3.Connection, window: Window) -> Shares:
    """{issue_id: {actor_key: {"delivery": points, "participation": points}}} from the stored impact build,
    for issues resolved in the window. Delivery is already net of the fix penalty."""
    out: Shares = {}
    for row in conn.execute(
        "SELECT issue_id, actor_key, delivery, participation FROM impact_share "
        "WHERE resolved_at >= ? AND resolved_at < ? ORDER BY issue_id, actor_key",
        (window.start, window.end),
    ):
        out.setdefault(row["issue_id"], {})[row["actor_key"]] = {
            "delivery": row["delivery"], "participation": row["participation"],
        }
    return out


def _counts(people: People, scope: Scope, key: str) -> bool:
    if scope.members is None:
        return True
    person = people.resolve(key)
    return person is not None and person in scope.members


def _points(conn: sqlite3.Connection, scope: Scope, window: Window, parts: tuple) -> Observations:
    people = People(conn)
    obs = Observations()
    outside = 0.0
    for shares in impact_shares(conn, window).values():
        for key, share in shares.items():
            value = sum(share[part] for part in parts)
            if value <= 0:
                continue
            if _counts(people, scope, key):
                obs.add(key, value)
            else:
                outside += value
    if outside > 1e-9:
        obs.notes.append(OUTSIDE_NOTE.format(points=round(outside, 2)))
    return obs


def impact_points(conn, scope: Scope, window: Window) -> Observations:
    return _points(conn, scope, window, ("delivery", "participation"))


def delivery_points(conn, scope: Scope, window: Window) -> Observations:
    return _points(conn, scope, window, ("delivery",))


def participation_points(conn, scope: Scope, window: Window) -> Observations:
    return _points(conn, scope, window, ("participation",))


def impact_per_dollar(conn, scope: Scope, window: Window) -> Observations:
    """Impact points over Claude cost (the cost_spent source), summed per person by the ratio aggregate."""
    obs = impact_points(conn, scope, window)
    ratio = Observations(notes=list(obs.notes))
    for key, values in obs.by_actor.items():
        for value in values:
            ratio.add_pair(key, value, 0.0, 1)
    cost = tk.cost_spent(conn, scope, window)
    for key, values in cost.by_actor.items():
        ratio.add_pair(key, 0.0, sum(values), 0)
    ratio.notes.extend(note for note in cost.notes if note not in ratio.notes)
    note = _no_cost_note(conn, scope, obs, cost)
    if note and note not in ratio.notes:
        ratio.notes.append(note)
    return ratio


NO_COST_NOTE = (
    "{n} of {m} people have no Claude cost linked, so Impact per dollar is blank for them (no Claude seat, "
    "or their Claude email is not linked to them: link it on the Teams screen)."
)


def _no_cost_note(conn, scope: Scope, impact: Observations, cost: Observations) -> Optional[str]:
    """Team scopes only: how many members with impact in the window have no Claude cost linked."""
    if scope.members is None:
        return None
    people = People(conn)
    earning = {people.resolve(key) for key in impact.by_actor}
    earning.discard(None)
    paid = {people.resolve(key) for key, values in cost.by_actor.items() if sum(values) > 0}
    missing = len(earning - paid)
    return NO_COST_NOTE.format(n=missing, m=len(earning)) if missing else None


def delivery_speed(conn, scope: Scope, window: Window) -> Observations:
    """Hours from an issue's start to the first linked PR merged after it, for each person who delivered."""
    people = People(conn)
    merges: Dict[str, List[str]] = defaultdict(list)
    for row in conn.execute(_MERGES_SQL):
        merges[row["issue_id"]].append(row["merged_at"])
    started = {row["source_id"]: row["started_at"] for row in _cohort(conn, window)}
    obs = Observations()
    for issue_id, shares in impact_shares(conn, window).items():
        start = started.get(issue_id)
        after = [m for m in merges.get(issue_id, []) if start and m > start]
        if not after:
            continue
        hours = hours_between(start, min(after))
        for key, share in shares.items():
            if share["delivery"] > 0 and _counts(people, scope, key):
                obs.add(key, hours)
    return obs


def durability(conn, scope: Scope, window: Window) -> Observations:
    """Delivered points on issues that were never reopened, over all delivered points."""
    people = People(conn)
    reopened = {
        row["record_id"] for row in all_rows(
            conn, "SELECT record_id, value FROM property WHERE record_kind = 'work_item' AND name = 'reopen_count'"
        ) if str(row["value"]).strip() not in ("", "0")
    }
    obs = Observations()
    for issue_id, shares in impact_shares(conn, window).items():
        for key, share in shares.items():
            if share["delivery"] > 0 and _counts(people, scope, key):
                kept = 0.0 if issue_id in reopened else share["delivery"]
                obs.add_pair(key, kept, share["delivery"], 1)
    return obs


def review_responsiveness(conn, scope: Scope, window: Window) -> Observations:
    """Hours from a pull request's creation to the person's first review event on it, per PR reviewed."""
    where, params = scope.repo_filter("c.repository_id")
    rows = conn.execute(
        "SELECT e.actor_account AS account, c.created_at AS created, MIN(e.occurred_at) AS first, "
        "MAX(CASE WHEN e.occurred_at >= ? AND e.occurred_at < ? THEN 1 ELSE 0 END) AS in_window "
        "FROM change_event e JOIN change_request c ON c.source = e.source AND c.source_id = e.change_request_id "
        "WHERE e.source = 'bitbucket' AND e.type IN ('comment', 'approved') AND e.actor_account IS NOT NULL "
        "AND (c.author_account IS NULL OR e.actor_account != c.author_account) "
        f"AND {where} GROUP BY e.actor_account, e.change_request_id",
        [window.start, window.end] + params,
    ).fetchall()
    obs = Observations(notes=bb._detail_note(conn, scope))
    for row in rows:
        hours = hours_between(row["created"], row["first"])
        if row["in_window"] and hours is not None and hours >= 0:
            obs.add(actor_key(("bitbucket", row["account"])), hours)
    return obs


def _reviews(conn: sqlite3.Connection, scope: Scope, window: Window) -> List[sqlite3.Row]:
    """Comments and approvals in the window on pull requests owned by someone else. The owner is compared by
    person, so a second linked account of the author earns no review credit on their own pull request."""
    return remembered(conn, ("reviews", scope.repos, window.start, window.end), lambda: _load_reviews(conn, scope, window))


def _load_reviews(conn: sqlite3.Connection, scope: Scope, window: Window) -> List[sqlite3.Row]:
    where, params = scope.repo_filter("c.repository_id")
    people = People(conn)
    rows = conn.execute(
        "SELECT e.actor_account AS account, e.change_request_id AS pr_id, e.type AS type, "
        "c.author_account AS author "
        "FROM change_event e JOIN change_request c ON c.source = e.source AND c.source_id = e.change_request_id "
        "WHERE e.source = 'bitbucket' AND e.type IN ('comment', 'approved') AND e.actor_account IS NOT NULL "
        "AND e.actor_account != '' AND e.occurred_at >= ? AND e.occurred_at < ? "
        f"AND {where} ORDER BY e.occurred_at, e.source_id",
        [window.start, window.end] + params,
    ).fetchall()
    return [row for row in rows if not _own_pr(people, row["account"], row["author"])]


def _own_pr(people: People, account: str, author: Optional[str]) -> bool:
    if not author:
        return False
    if account == author:
        return True
    reviewer = people.resolve(actor_for(account))
    return reviewer is not None and reviewer == people.resolve(actor_for(author))


def prs_reviewed(conn, scope: Scope, window: Window) -> Observations:
    """Distinct pull requests owned by others where the person left at least one comment in the window."""
    seen = set()
    obs = Observations(notes=bb._detail_note(conn, scope))
    for row in _reviews(conn, scope, window):
        if row["type"] == "comment" and (row["account"], row["pr_id"]) not in seen:
            seen.add((row["account"], row["pr_id"]))
            obs.add(actor_for(row["account"]), 1.0)
    return obs


def review_value(conn, scope: Scope, window: Window) -> Observations:
    """Comments plus half a point per approval on other people's pull requests in the window."""
    obs = Observations(notes=bb._detail_note(conn, scope))
    for row in _reviews(conn, scope, window):
        obs.add(actor_for(row["account"]), 1.0 if row["type"] == "comment" else 0.5)
    return obs


def review_follow_through(conn, scope: Scope, window: Window) -> Observations:
    return bb.review_response_rate(conn, scope, window)
