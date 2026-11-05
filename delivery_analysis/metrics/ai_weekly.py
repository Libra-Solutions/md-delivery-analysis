"""Weekly Claude cost, active days and points for one person (T12)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window, week_start

_USAGE_SQL = (
    "SELECT COALESCE(SUM(cost_usd), 0) AS cost, COUNT(DISTINCT CASE WHEN cost_usd > 0 THEN day END) AS active "
    "FROM token_usage WHERE person_id = ? AND day >= ? AND day < ?"
)


def _points(conn, person_id: str, first: date, last: date, tz) -> float:
    metric = replace(BY_NAME["story_points_done"], windowed=False)
    window = make_window("custom", tz, last, start=first.isoformat(), end=last.isoformat())
    result = run_metric(conn, metric, Scope(), window)
    for row in result.get("rows", []):
        if row.get("person_id") == person_id and row.get("value") is not None:
            return float(row["value"])
    return 0.0


def weekly(conn, person_id: str, start: date, end: date, tz) -> dict:
    """Monday-based weeks covering [start, end); the first and last week are clipped to that range."""
    first_use = conn.execute(
        "SELECT MIN(day) AS first FROM token_usage WHERE person_id = ? AND cost_usd > 0", (person_id,)
    ).fetchone()["first"]
    weeks: List[Dict[str, Any]] = []
    monday = week_start(start)
    while monday < end:
        first = max(monday, start)
        after = min(monday + timedelta(days=7), end)
        usage = conn.execute(_USAGE_SQL, (person_id, first.isoformat(), after.isoformat())).fetchone()
        weeks.append({
            "week": monday.isoformat(),
            "cost_usd": round(float(usage["cost"] or 0.0), 2),
            "active_days": int(usage["active"] or 0),
            "points": round(_points(conn, person_id, first, after - timedelta(days=1), tz), 2),
        })
        monday += timedelta(days=7)
    starts: Optional[str] = first_use
    return {"starts": starts, "weeks": weeks}
