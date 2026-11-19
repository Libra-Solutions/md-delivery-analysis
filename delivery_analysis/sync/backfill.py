"""Backfill: fetch Jira and Bitbucket further back than the normal sync window.

History already stored is not fetched again. For each scope the backfill works out which stretches of
[requested start, saved cursor] are stored, from:
- the ranges earlier syncs recorded (`fetched_range`);
- the stretch an earlier backfill finished (`backfill_state`);
- for Bitbucket, the stored pull requests themselves: a run of pull requests with no silence longer than
  `PR_GAP_DAYS` counts as stored. This only matters for data fetched before ranges were recorded.

Then, per scope:
- no hole: the cursor is kept, so only new data is read;
- a hole that starts after the requested start: the cursor moves back to the start of the first hole, so the sync
  reads from there and nothing older is fetched again;
- nothing stored: the cursor is cleared and the whole window is read.

Connectors read "everything changed since a date", so a hole is filled by reading from its start to now.
Sources that are not set up are never touched. `force` fetches everything again.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import timedelta
from typing import Callable, Dict, List, Optional, Tuple

from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.settings import BITBUCKET_BUDGET_MAX
from delivery_analysis.store import backfill_state, fetched_range, sync_state
from delivery_analysis.sync.lock import CLI_WAIT_SECONDS, sync_lock
from delivery_analysis.sync.runner import shift_cursor, utc_now_iso
from delivery_analysis.sync.service import sync_and_reconcile

MIN_DAYS = 1
MAX_DAYS = 3650
# Their cursors are reset so the wider window is read. The Claude cost report is not: it re-reads its own window.
RESET_CONNECTORS = ("jira", "bitbucket")
# With --until-done the run is bounded by time, not requests.
UNLIMITED_REQUESTS = 10_000_000
MAX_PATIENCE_HOURS = 48
# Pull requests further apart than this leave a stretch that may be a hole, so it is fetched again to be sure.
PR_GAP_DAYS = 21


def _pull_request_runs(conn: sqlite3.Connection, scope: str, since: str, cursor: str) -> List[Tuple[str, str]]:
    """Stretches of [since, cursor] that stored pull requests cover without a long silence.

    Jira has no equivalent: it syncs by update time, so old tickets do not prove old history was fetched."""
    rows = conn.execute(
        "SELECT created_at FROM change_request WHERE source = 'bitbucket' AND repository_id = ? "
        "AND created_at IS NOT NULL AND created_at <= ? ORDER BY created_at",
        (scope, cursor),
    ).fetchall()
    points = [row["created_at"] for row in rows] + [cursor]
    gap = timedelta(days=PR_GAP_DAYS)
    return [(a, b) for a, b in zip(points, points[1:])
            if fetched_range.parse(b) - fetched_range.parse(a) <= gap]


def stored_ranges(conn: sqlite3.Connection, connector: str, scope: str, since: str,
                  cursor: str) -> List[Tuple[str, str]]:
    """Every stretch this scope's history is known to be stored for, merged."""
    ranges = list(fetched_range.list_ranges(conn, connector, scope))
    done = backfill_state.get_range(conn, connector, scope)
    if done:
        ranges.append(done)
    if connector == "bitbucket":
        ranges.extend(_pull_request_runs(conn, scope, since, cursor))
    return fetched_range.merge(ranges)


def fetch_from(conn: sqlite3.Connection, connector: str, scope: str, since: str,
               cursor: Optional[str]) -> Optional[str]:
    """Where this scope's backfill has to start: None when nothing is missing, `since` for the whole window,
    or the start of the first hole."""
    if not cursor:
        return since
    hole = fetched_range.first_gap(stored_ranges(conn, connector, scope, since, cursor), since, cursor)
    if hole is None:
        return None
    return since if fetched_range.parse(hole) <= fetched_range.parse(since) + fetched_range.TOUCH else hole


def _plan(conn: sqlite3.Connection, names: List[str], since: str, force: bool,
          log: Callable[[str], None]) -> Dict[Tuple[str, str], Optional[str]]:
    """Move or clear the cursors of scopes that still need history.

    Returns {(connector, scope): cursor the backfill left}, for every scope it changed."""
    planned: Dict[Tuple[str, str], Optional[str]] = {}
    with conn:
        for name in names:
            rows = conn.execute("SELECT scope, cursor FROM sync_state WHERE connector = ?", (name,)).fetchall()
            for row in rows:
                scope = row["scope"]
                start = since if force else fetch_from(conn, name, scope, since, row["cursor"])
                if start is None:
                    log(f"{name}/{scope}: stored back to {since[:10]} with no gaps, only new data is fetched")
                elif start == since:
                    sync_state.clear_state(conn, name, scope)
                    planned[(name, scope)] = None
                else:
                    log(f"{name}/{scope}: missing data from {start[:10]}, fetching from there")
                    sync_state.set_cursor(conn, name, scope, start)
                    planned[(name, scope)] = start
    return planned


def backfill(
    conn: sqlite3.Connection,
    settings,
    environ: dict,
    days: int,
    only: str = None,
    log=print,
    transport=None,
    force: bool = False,
    now: Callable[[], str] = utc_now_iso,
    budget: Optional[int] = None,
    until_done_hours: Optional[float] = None,
    lock_wait: float = CLI_WAIT_SECONDS,
) -> tuple:
    """Return sync_and_reconcile's (results, team summary lines, failed team count).

    `budget` overrides the Bitbucket request budget for this run only. `until_done_hours` drops the budget and
    paces against Bitbucket's rate limit instead: each limit is waited out and the run goes on, until everything
    is fetched or that many hours have passed. Whatever is left carries over to the next run."""
    if not isinstance(days, int) or days < MIN_DAYS or days > MAX_DAYS:
        raise ValueError(f"--days must be between {MIN_DAYS} and {MAX_DAYS}.")
    if budget is not None and (not isinstance(budget, int) or budget < 1 or budget > BITBUCKET_BUDGET_MAX):
        raise ValueError(f"--budget must be between 1 and {BITBUCKET_BUDGET_MAX}.")
    if until_done_hours is not None and not (0 < until_done_hours <= MAX_PATIENCE_HOURS):
        raise ValueError(f"--max-hours must be more than 0 and at most {MAX_PATIENCE_HOURS}.")
    emit = log or (lambda _line: None)
    chosen = budget if budget is not None else settings.bitbucket_budget
    patience = settings.bitbucket_patience_hours
    if until_done_hours is not None:
        chosen, patience = UNLIMITED_REQUESTS, until_done_hours
    wide = dataclasses.replace(settings, window_days=days, bitbucket_budget=chosen,
                               bitbucket_patience_hours=patience)
    connectors = build_connectors(wide, environ, transport)
    if until_done_hours is not None:
        emit(f"bitbucket: no request budget; rate limits are waited out for up to {until_done_hours:g} hours")
        for connector in connectors:
            client = getattr(connector, "_client", None)
            if client is not None and hasattr(client, "on_wait"):
                client.on_wait = lambda seconds, name=connector.name: emit(
                    f"{name}: rate limited, waiting {seconds:.0f}s before carrying on")
    built = {c.name for c in connectors}
    wanted = [name for name in RESET_CONNECTORS if only is None or only == name]
    for name in wanted:
        if name not in built:
            emit(f"{name}: not set up, so nothing is fetched and its saved position is kept")
    names = [name for name in wanted if name in built]
    since = shift_cursor(now(), days)
    known = {(name, row["scope"]) for name in names
             for row in conn.execute("SELECT scope FROM sync_state WHERE connector = ?", (name,))}
    with sync_lock(conn, wait_seconds=lock_wait, on_wait=lambda: emit(
            "another sync or backfill is running on this database (the app's refresh?); waiting for it to finish")):
        planned = _plan(conn, names, since, force, emit)
        # The sync itself keeps the original settings, so the token and cost window is unchanged.
        outcome = sync_and_reconcile(conn, connectors, settings, environ, only=only, log=log)
        finished = now()
        for name in names:
            rows = conn.execute("SELECT scope, cursor, status FROM sync_state WHERE connector = ?", (name,)).fetchall()
            for row in rows:
                key = (name, row["scope"])
                fetched = key in planned or key not in known  # skipped scopes read only new data
                # A run cut short by the request budget leaves the cursor where the backfill put it (or none).
                if not fetched or row["status"] != "ok" or not row["cursor"] or row["cursor"] == planned.get(key):
                    continue
                backfill_state.mark_done(conn, name, row["scope"], since, finished)
    return outcome
