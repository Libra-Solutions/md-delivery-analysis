"""AI year: twelve calendar months per person, split at their first Claude use (their AI start).

The numbers come from the uplift engine (`run_metric` over custom windows), so they match the AI uplift and
rankings screens. A month is "since AI" when it holds or follows the AI start. Nothing is projected: the running
month shows what has happened so far, and it is left out of the before and after medians because it is not a
whole month.
"""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from delivery_analysis.metrics import blocks, uplift, verdicts
from delivery_analysis.metrics.people import People

MONTHS = 12
SHORT_BASELINE = 6
BEFORE, SINCE, YEAR = "Before AI", "Since AI", "Last 12 months"
POINTS = "story_points_done"


def ai_start(conn: sqlite3.Connection, person_id: str) -> Optional[date]:
    """The first day with Claude cost for this person, or None."""
    row = conn.execute(
        "SELECT min(day) AS first FROM token_usage WHERE person_id = ? AND cost_usd > 0", (person_id,)
    ).fetchone()
    return date.fromisoformat(row["first"][:10]) if row and row["first"] else None


def claude_data_start(conn: sqlite3.Connection) -> Optional[date]:
    """The first day of any Claude cost data; an AI start on this day may really be earlier."""
    row = conn.execute("SELECT min(day) AS first FROM claude_usage_day WHERE cost_usd > 0").fetchone()
    return date.fromisoformat(row["first"][:10]) if row and row["first"] else None


def _month_index(start: date, anchor: date) -> int:
    return (start.year - anchor.year) * 12 + (start.month - anchor.month)


def month_blocks(today: date, anchor: Optional[date], back: int = MONTHS) -> List[Dict[str, Any]]:
    """The `back` calendar months ending with today's (running) month.

    `index` counts months from the AI start's month (0 = that month, negative = before); with no AI start
    every month is negative, so all of them read as before."""
    out: List[Dict[str, Any]] = []
    year, month = today.year, today.month
    for k in range(back - 1, -1, -1):
        y, m = divmod(year * 12 + (month - 1) - k, 12)
        start = date(y, m + 1, 1)
        length = calendar.monthrange(start.year, start.month)[1]
        end = min(start + timedelta(days=length - 1), today)
        seen = (end - start).days + 1
        out.append({
            "index": _month_index(start, anchor) if anchor else -(k + 1),
            "first": start.isoformat(), "days": seen, "month_days": length, "partial": seen < length,
        })
    return out


def person_months(conn, person_id: str, scope, metric_name: str, start: Optional[date], today: date, tz,
                  group: Optional[Sequence[str]] = None) -> dict:
    """Same shape as `uplift.person_blocks`, with calendar months in place of 30-day blocks."""
    metric = uplift._metric(metric_name)
    people = People(conn)
    population = uplift._population(scope, people)
    pool = uplift._pool(population, group)
    rows: List[Dict[str, Any]] = []
    mine: Dict[int, Optional[float]] = {}
    everyone: Dict[int, List[float]] = {}
    for block in month_blocks(today, start):
        first = date.fromisoformat(block["first"])
        values = uplift._values(conn, metric, scope, people, population, tz, today, first, block["days"], person_id)
        index = block["index"]
        hole = uplift.is_hole(metric, values, pool, person_id)
        value = None if hole else values.get(person_id)
        present = [] if hole else uplift._present(uplift._take(values, pool))
        if not block["partial"]:  # the running month is not a whole month, so it stays out of the medians
            mine[index], everyone[index] = value, present
        stats = blocks.summarize(present)
        rows.append({
            "index": index, "start": block["first"][:7], "days": block["days"], "partial": block["partial"],
            "value": uplift._round(value), "median": uplift._round(stats["median"]),
            "average": uplift._round(stats["average"]), "no_data": hole,
        })
    own = {"before": uplift._summary([v for i, v in mine.items() if i < 0]),
           "after": uplift._summary([v for i, v in mine.items() if i >= 0])}
    pooled = {"before": uplift._summary([v for i, vs in everyone.items() if i < 0 for v in vs]),
              "after": uplift._summary([v for i, vs in everyone.items() if i >= 0 for v in vs])}
    return {
        "metric": metric_name, "label": metric.label, "unit": metric.unit, "better": metric.better,
        "blocks": rows, "person": own, "everyone": pooled,
        "short_baseline": len(uplift._present(v for i, v in mine.items() if i < 0)) < SHORT_BASELINE,
        "effect": effect(own, pooled),
    }


def _change(before: Optional[float], after: Optional[float]) -> Dict[str, Optional[float]]:
    if before is None or after is None:
        return {"change": None, "ratio": None}
    return {"change": round(after - before, 2), "ratio": None if before == 0 else round(after / before, 2)}


def effect(own: Dict[str, Any], pooled: Dict[str, Any]) -> Dict[str, Any]:
    """Before-to-since change in median and average, for the person and for the comparison group.

    `vs_group` is the person's median ratio minus the group's: above 0 means they rose more than the group."""
    out: Dict[str, Any] = {}
    for who, summary in (("person", own), ("group", pooled)):
        out[who] = {stat: _change((summary.get("before") or {}).get(stat), (summary.get("after") or {}).get(stat))
                    for stat in ("median", "average")}
    mine, theirs = out["person"]["median"]["ratio"], out["group"]["median"]["ratio"]
    out["vs_group"] = None if mine is None or theirs is None else round(mine - theirs, 2)
    return out


def periods(today: date, start: Optional[date]) -> List[Dict[str, Any]]:
    """Before AI and Since AI as day ranges inside the twelve months (or one "Last 12 months" with no start)."""
    first = date.fromisoformat(month_blocks(today, start)[0]["first"])
    if start is None:
        return [{"label": YEAR, "first": first, "days": (today - first).days + 1}]
    out = []
    if start > first:
        out.append({"label": BEFORE, "first": first, "days": (start - first).days})
    if start <= today:
        since = max(start, first)
        out.append({"label": SINCE, "first": since, "days": (today - since).days + 1})
    return out


def _window_value(conn, metric_name, person_id, scope, people, population, tz, today, first, days, pool):
    metric = uplift._metric(metric_name)
    values = uplift._values(conn, metric, scope, people, population, tz, today, first, days, person_id)
    if uplift.is_hole(metric, values, pool, person_id):
        return None, None  # nobody has any in this period: no data, so "Cannot see" rather than a zero
    stats = blocks.summarize(uplift._present(uplift._take(values, pool)))
    return values.get(person_id), stats["median"]


def expectations(conn, person_id: str, scope, level: str, start: Optional[date], today: date, tz,
                 points: dict, group: Optional[Sequence[str]] = None, who: str = "everyone") -> List[Dict[str, Any]]:
    """The level expectations (AI-agnostic) judged on each period with the 30/60/90 verdict words.

    `points` is this person's `person_months` for story points: pace is their median month in the period
    against their own Before AI median and the comparison group's median month in that period."""
    people = People(conn)
    population = uplift._population(scope, people)
    pool = uplift._pool(population, group)
    own_before = (points["person"].get("before") or {}).get("median")
    out: List[Dict[str, Any]] = []
    before_comments: Optional[float] = None
    for period in periods(today, start):
        first, days = period["first"], period["days"]
        side = "after" if period["label"] == SINCE else "before"
        if days < 1:
            continue

        def val(name):
            return _window_value(conn, name, person_id, scope, people, population, tz, today, first, days, pool)

        tests, _ = val("prs_with_tests")
        durability, _ = val("durability")
        comments, group_comments = val("comments_received_per_pr")
        inline, _ = val("inline_comments_given")
        big, _ = val("big_tickets")
        compare_comments = before_comments
        if period["label"] != SINCE:
            before_comments, compare_comments = comments, group_comments
        facts = {
            "pace_per30": (points["person"].get(side) or {}).get("median"),
            "before_median": own_before,
            "median_per30": (points["everyone"].get(side) or {}).get("median"),
            "tests_share": tests, "durability": durability,
            "comments_per_pr": comments, "before_comments_per_pr": compare_comments,
            "inline_comments": None if inline is None else round(inline * 30.0 / days, 2),
            "big_tickets": big,
        }
        items = verdicts.verdicts(level, period["label"], facts)
        for item in items:
            if item["item"] == "Pace":
                item["threshold"] = item["threshold"].replace("own before median", "own Before AI median") \
                    .replace("the median of everyone", f"the median month of {who}")
            elif item["item"] == "Review comments per PR" and period["label"] != SINCE:
                item["threshold"] = item["threshold"].replace("own before level", f"the median of {who}")
            elif item["item"] == "Review comments per PR":
                item["threshold"] = item["threshold"].replace("own before level", "own Before AI level")
            elif item["item"] == "Inline comments given":
                item["threshold"] = item["threshold"] + " per 30 days"
        out.append({"label": period["label"], "first": first.isoformat(), "days": days, "items": items})
    return out
