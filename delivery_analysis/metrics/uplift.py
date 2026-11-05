"""Uplift engine: 30-day blocks around Day 0 for one person against everyone, plus Days 1-30/60/90 windows.

Every number comes from `run_metric` (the same code path as the rankings) over custom date windows. Sum metrics
count 0 for people without a row and a running block is pro-rated to a full block; other metrics never are.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from delivery_analysis.metrics import blocks
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import People
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window

BLOCK_DAYS = 30
WINDOW_DAYS = (30, 60, 90)
SHORT_BASELINE = 6


def _round(value: Optional[float], places: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), places)


def _population(scope, people: People) -> List[str]:
    if scope.members is not None:
        return [pid for pid in scope.members if not people.is_excluded(pid)]
    return [row["person_id"] for row in people.all()]


def _pool(population: List[str], group: Optional[Sequence[str]]) -> Optional[List[str]]:
    """The people whose values make the median and average; None means everyone in `population`.

    A group is limited to people in `population`; with nobody left it falls back to everyone, as series.py does."""
    if group is None:
        return None
    wanted = set(group)
    chosen = [pid for pid in population if pid in wanted]
    return chosen or None


def _take(values: Dict[str, Optional[float]], pool: Optional[List[str]]) -> Iterable[Optional[float]]:
    return values.values() if pool is None else [values.get(pid) for pid in pool]


_local = threading.local()


def _metric_rows(conn: sqlite3.Connection, metric, scope, people: People, tz, today: date, first: date,
                 days: int):
    """(ok, {person_id: value}) for one window, cached per connection: one request asks for the same window
    many times (people sharing a Day 0, graphs and tables sharing blocks), and its data cannot change."""
    if getattr(_local, "conn", None) is not conn:
        _local.conn, _local.cache = conn, {}
    key = (metric.name, metric.aggregate, repr(scope), str(tz), today, first, days)
    if key not in _local.cache:
        window = make_window("custom", tz, today, start=first.isoformat(),
                             end=(first + timedelta(days=max(days, 1) - 1)).isoformat())
        result = run_metric(conn, replace(metric, windowed=False), scope, window, people)
        ok = result["status"] == "ok"
        have = {row["person_id"]: row["value"] for row in result["rows"] if row["person_id"] is not None} if ok else {}
        _local.cache[key] = (ok, have)
    return _local.cache[key]


def _values(conn: sqlite3.Connection, metric, scope, people: People, population: List[str], tz, today: date,
            first: date, days: int, person_id: str) -> Dict[str, Optional[float]]:
    """Per-person value over `days` local days from `first`; unmapped accounts never appear."""
    ok, have = _metric_rows(conn, metric, scope, people, tz, today, first, days)
    everyone = list(population)
    if person_id not in everyone:
        everyone.append(person_id)
    out: Dict[str, Optional[float]] = {}
    for pid in everyone:
        value = have.get(pid)
        if value is None and ok and metric.aggregate == "sum":
            value = 0.0
        out[pid] = value
    return out


def is_hole(metric, values: Dict[str, Optional[float]], pool: Optional[List[str]], person_id: str) -> bool:
    """True when a sum metric is 0 for the person and for everyone in the comparison pool.

    That is a stretch the data does not cover (a repository not yet selected, history not fetched), not a month
    of real zero output, so it is shown as "no data" and left out of the before and after figures."""
    if metric.aggregate != "sum":
        return False
    pooled = _present(_take(values, pool))
    return bool(pooled) and all(v == 0 for v in pooled) and not values.get(person_id)


def _present(values) -> List[float]:
    return [float(v) for v in values if v is not None]


def _summary(values) -> Dict[str, Any]:
    summary = blocks.summarize(_present(values))
    return {key: (val if key == "count" else _round(val)) for key, val in summary.items()}


def _metric(name: str):
    if name not in BY_NAME:
        raise KeyError(f"Unknown metric {name!r}.")
    return BY_NAME[name]


def person_blocks(conn, person_id: str, scope, metric_name: str, day0: date, today: date, tz,
                  group: Optional[Sequence[str]] = None) -> dict:
    """`group` limits "everyone" (the median and average) to those people; the person's own values never change."""
    metric = _metric(metric_name)
    people = People(conn)
    population = _population(scope, people)
    pool = _pool(population, group)
    is_sum = metric.aggregate == "sum"
    rows: List[Dict[str, Any]] = []
    mine: Dict[int, Optional[float]] = {}
    everyone: Dict[int, List[float]] = {}
    for block in blocks.block_dates(day0, today):
        first = date.fromisoformat(block["first"])
        values = _values(conn, metric, scope, people, population, tz, today, first, block["days"], person_id)
        if is_sum and block["partial"]:
            values = {pid: None if v is None else blocks.prorate(v, block["days"], BLOCK_DAYS)
                      for pid, v in values.items()}
        index = block["index"]
        hole = is_hole(metric, values, pool, person_id)
        mine[index] = None if hole else values.get(person_id)
        everyone[index] = [] if hole else _present(_take(values, pool))
        stats = blocks.summarize(everyone[index])
        rows.append({
            "index": index, "start": block["first"], "days": block["days"], "partial": block["partial"],
            "value": _round(mine[index]), "median": _round(stats["median"]), "average": _round(stats["average"]),
            "no_data": hole,
        })
    own = {
        "before": _summary([v for i, v in mine.items() if i < 0]),
        "after": _summary([v for i, v in mine.items() if i >= 0]),
    }
    pooled = {
        "before": _summary([v for i, vs in everyone.items() if i < 0 for v in vs]),
        "after": _summary([v for i, vs in everyone.items() if i >= 0 for v in vs]),
    }
    before_count = len(_present(v for i, v in mine.items() if i < 0))
    return {
        "metric": metric_name, "label": metric.label, "unit": metric.unit, "better": metric.better,
        "blocks": rows, "person": own, "everyone": pooled,
        "short_baseline": before_count < SHORT_BASELINE,
    }


def _before_median(conn, person_id, scope, metric, people, population, day0, today, tz, pool=None):
    """The person's median over their before blocks (the uplift baseline) and everyone's pooled median."""
    mine: List[Optional[float]] = []
    pooled: List[float] = []
    for block in blocks.block_dates(day0, today):
        if block["index"] >= 0:
            continue
        values = _values(conn, metric, scope, people, population, tz, today,
                         date.fromisoformat(block["first"]), block["days"], person_id)
        if is_hole(metric, values, pool, person_id):
            continue  # no data, not a zero: it must not drag the baseline down
        mine.append(values.get(person_id))
        pooled.extend(_present(_take(values, pool)))
    return blocks.summarize(_present(mine))["median"], blocks.summarize(pooled)["median"]


def _windows(conn, person_id, scope, metric, people, population, day0, today, tz, before,
             pool=None) -> List[Dict[str, Any]]:
    is_sum = metric.aggregate == "sum"
    reached = blocks.day_reached(day0, today)
    out: List[Dict[str, Any]] = []
    for size in WINDOW_DAYS:
        seen = min(size, reached)
        if seen < 1 or (size == 90 and reached < 60):
            continue  # Days 1-90 only once Day 60 is reached
        values = _values(conn, metric, scope, people, population, tz, today, day0, seen, person_id)
        complete = reached >= size
        if is_sum and not complete:
            scaled = {pid: None if v is None else blocks.prorate(v, seen, size) for pid, v in values.items()}
        else:
            scaled = values
        prorated = scaled.get(person_id)
        stats = blocks.summarize(_present(_take(scaled, pool)))
        rate = None if prorated is None else (prorated * BLOCK_DAYS / size if is_sum else prorated)
        uplift = None if rate is None or not before else round(rate / before, 2)
        out.append({
            "label": f"Days 1-{size}", "start": day0.isoformat(), "days": size, "reached": seen,
            "complete": complete, "total": _round(values.get(person_id)), "prorated": _round(prorated),
            "median": _round(stats["median"]), "average": _round(stats["average"]),
            "before_median": _round(before), "uplift": uplift,
        })
    return out


def windows(conn, person_id: str, scope, metric_name: str, day0: date, today: date, tz,
            group: Optional[Sequence[str]] = None) -> list:
    metric = _metric(metric_name)
    people = People(conn)
    population = _population(scope, people)
    pool = _pool(population, group)
    before, _ = _before_median(conn, person_id, scope, metric, people, population, day0, today, tz, pool)
    return _windows(conn, person_id, scope, metric, people, population, day0, today, tz, before, pool)


def metric_table(conn, person_id: str, scope, metric_names: list, day0: date, today: date, tz,
                 group: Optional[Sequence[str]] = None) -> list:
    people = People(conn)
    population = _population(scope, people)
    pool = _pool(population, group)
    table: List[Dict[str, Any]] = []
    for name in metric_names:
        metric = _metric(name)
        before, pooled = _before_median(conn, person_id, scope, metric, people, population, day0, today, tz, pool)
        per_window = []
        for win in _windows(conn, person_id, scope, metric, people, population, day0, today, tz, before, pool):
            scale = BLOCK_DAYS / win["days"] if metric.aggregate == "sum" else 1.0
            value, median = win["prorated"], win["median"]
            per_window.append({
                "label": win["label"], "value": _round(None if value is None else value * scale),
                "median": _round(None if median is None else median * scale), "uplift": win["uplift"],
            })
        table.append({
            "metric": name, "label": metric.label, "before": _round(before),
            "before_median_everyone": _round(pooled), "windows": per_window,
        })
    return table
