"""Review metrics: comments received on merged PRs, inline comments given, teammates reviewed."""

from __future__ import annotations

import sqlite3

from delivery_analysis.metrics.people import Scope, actor_key
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window


def comments_received_per_pr(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """Per merged PR (by merge date): top-level comments by others; the ratio is comments over PRs."""
    where, params = scope.repo_filter("c.repository_id")
    obs = Observations()
    rows = conn.execute(
        "SELECT c.author_account, (SELECT COUNT(*) FROM review_comment r "
        " WHERE r.source = 'bitbucket' AND r.change_request_id = c.source_id AND r.parent_id IS NULL "
        " AND r.actor_account IS NOT NULL AND r.actor_account != COALESCE(c.author_account, '')) AS n "
        "FROM change_request c WHERE c.source = 'bitbucket' AND c.state = 'MERGED' "
        f"AND c.merged_at >= ? AND c.merged_at < ? AND {where}",
        [window.start, window.end] + params,
    ).fetchall()
    for row in rows:
        obs.add_pair(actor_key(("bitbucket", row["author_account"])), row["n"], 1.0)
    return obs


def inline_comments_given(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """Inline (file) comments on other people's PRs, by comment date."""
    where, params = scope.repo_filter("c.repository_id")
    obs = Observations()
    for row in conn.execute(
        "SELECT r.actor_account FROM review_comment r "
        "JOIN change_request c ON c.source = r.source AND c.source_id = r.change_request_id "
        "WHERE r.source = 'bitbucket' AND r.path IS NOT NULL AND r.actor_account IS NOT NULL "
        "AND r.actor_account != COALESCE(c.author_account, '') "
        f"AND r.created_at >= ? AND r.created_at < ? AND {where}",
        [window.start, window.end] + params,
    ):
        obs.add(actor_key(("bitbucket", row["actor_account"])))
    return obs


def teammates_reviewed(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """Distinct PR authors a person commented on or approved for in the window (one value per person)."""
    where, params = scope.repo_filter("c.repository_id")
    seen = {}
    for row in conn.execute(
        "SELECT DISTINCT e.actor_account AS reviewer, c.author_account AS author FROM change_event e "
        "JOIN change_request c ON c.source = e.source AND c.source_id = e.change_request_id "
        "WHERE e.source = 'bitbucket' AND e.type IN ('comment', 'approved') "
        "AND e.actor_account IS NOT NULL AND c.author_account IS NOT NULL "
        "AND e.actor_account != c.author_account "
        f"AND e.occurred_at >= ? AND e.occurred_at < ? AND {where}",
        [window.start, window.end] + params,
    ):
        seen.setdefault(row["reviewer"], set()).add(row["author"])
    obs = Observations()
    for reviewer, authors in seen.items():
        obs.add(actor_key(("bitbucket", reviewer)), len(authors))
    return obs
