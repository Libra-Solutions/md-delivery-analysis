"""Ticket metrics: big tickets and points dated by the linked pull request's merge."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from delivery_analysis.metrics.credit import credit_for, first_merges
from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window

BIG_POINTS = 8.0
_EARLIEST = "0001-01-01T00:00:00Z"
_LATEST = "9999-12-31T00:00:00Z"


def _counts(people: People, scope: Scope, key: str) -> bool:
    return scope.members is None or people.resolve(key) in scope.members


def big_tickets(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """Completed tickets of 8 or more points; a shared ticket counts by each author's share."""
    credit = credit_for(conn, window)
    people = People(conn)
    obs = Observations()
    for row in credit.issues:
        points = row["story_points"]
        if points is None or points < BIG_POINTS:
            continue
        for key, share in (credit.shares.get(row["source_id"]) or {}).items():
            if key and _counts(people, scope, key):
                obs.add(key, share)
    return obs


def points_by_merge_date(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    """Story points of delivered tickets, dated by the earliest merge of their linked pull requests.

    A ticket with no merged linked pull request is dated by when it was delivered.
    """
    credit = credit_for(conn, replace(window, start=_EARLIEST, end=_LATEST))
    merges = first_merges(conn)
    people = People(conn)
    obs = Observations()
    for row in credit.issues:
        when = merges.get(row["source_id"]) or row["resolved_at"]
        if not when or not (window.start <= when < window.end) or row["story_points"] is None:
            continue
        for key, share in (credit.shares.get(row["source_id"]) or {}).items():
            if key and _counts(people, scope, key):
                obs.add(key, row["story_points"] * share)
    return obs
