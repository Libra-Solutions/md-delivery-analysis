"""Story points per calendar week for one person, with the median and average of the comparison group.

Plain points under the Director's rule (`credit.credit_for`): each ticket counts in the week it was first
delivered, split by its credit shares. No impact weighting, penalties or rolling windows.
"""

from __future__ import annotations

import statistics
import sqlite3
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional, Sequence

from delivery_analysis.metrics.credit import credit_for
from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.window import make_window, week_start


def _local_day(iso: str, tz: tzinfo) -> date:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz).date()


def weekly_points(
    conn: sqlite3.Connection, person_id: str, scope: Scope, *, end: date, weeks: int = 26,
    tz: Optional[tzinfo] = None, group: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """`group` limits the median and average to the chosen people; None, or nobody in scope, means everyone
    in scope. People in the group with no points in a week count as 0 that week."""
    tz = tz or timezone.utc
    people = People(conn)
    last_week = week_start(end)
    first_week = last_week - timedelta(weeks=weeks - 1)
    window = make_window("custom", tz, end, start=first_week.isoformat(), end=end.isoformat())
    everyone = list(scope.members) if scope.members is not None else [row["person_id"] for row in people.all()]
    chosen = [member for member in (group or []) if member in everyone]
    members = chosen or everyone
    totals: Dict[date, Dict[str, float]] = {first_week + timedelta(weeks=k): {} for k in range(weeks)}
    credit = credit_for(conn, window)
    for row in credit.issues:
        points = row["story_points"]
        if not points or not row["resolved_at"]:
            continue
        week = week_start(_local_day(row["resolved_at"], tz))
        if week not in totals:
            continue
        for key, share in (credit.shares.get(row["source_id"]) or {}).items():
            pid = people.resolve(key)
            if pid:
                totals[week][pid] = totals[week].get(pid, 0.0) + points * share
    mine: List[float] = []
    medians: List[Optional[float]] = []
    averages: List[Optional[float]] = []
    for week in sorted(totals):
        have = totals[week]
        mine.append(round(have.get(person_id, 0.0), 2))
        values = [have.get(member, 0.0) for member in members]
        medians.append(round(statistics.median(values), 2) if values else None)
        averages.append(round(statistics.fmean(values), 2) if values else None)
    return {
        "weeks": [week.isoformat() for week in sorted(totals)],
        "points": mine, "median": medians, "average": averages,
        "running": last_week.isoformat(),  # the current week is still in progress
        "comparison": {"custom": bool(chosen), "size": len(members)},
    }
