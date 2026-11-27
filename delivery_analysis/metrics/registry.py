from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.window import ISO_Z, Window, previous
from delivery_analysis.store.db import remembered

PER_PERSON = "per_person"
TEAM_SERIES = "team_series"
TEAM_BREAKDOWN = "team_breakdown"

SOURCE_PROBES = {
    "bitbucket": "SELECT 1 FROM change_request WHERE source = 'bitbucket' "
    "UNION ALL SELECT 1 FROM vcs_commit WHERE source = 'bitbucket' LIMIT 1",
    "jira": "SELECT 1 FROM work_item LIMIT 1",
    "claude_usage": "SELECT 1 FROM claude_usage_day LIMIT 1",
    "links": "SELECT 1 FROM link LIMIT 1",
    "confluence": "SELECT 1 FROM document LIMIT 1",
}

# Metric needs that are backed by raw payloads, mapped to the raw_payload source.
COVERAGE_SOURCES = {"bitbucket": "bitbucket", "jira": "jira"}


@dataclass
class Observations:
    """Raw values per actor key (see people.actor_key) plus data-quality notes.

    Ratio metrics use `add_pair` instead of `add`: the value is sum of numerators / sum of denominators.
    `confidence` and `unranked` are keyed like the observations and pass through to the rows.
    """

    by_actor: Dict[str, List[float]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    pairs: Dict[str, List[Tuple[float, float, int]]] = field(default_factory=dict)
    confidence: Dict[str, str] = field(default_factory=dict)
    unranked: Dict[str, str] = field(default_factory=dict)

    def add(self, key: Optional[str], value: float = 1.0) -> None:
        if key:
            self.by_actor.setdefault(key, []).append(float(value))

    def add_pair(self, key: Optional[str], numerator: float, denominator: float, sample: int = 1) -> None:
        if key:
            self.pairs.setdefault(key, []).append((float(numerator), float(denominator), int(sample)))


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: str
    kind: str
    needs: Tuple[str, ...]
    better: str = "higher"
    aggregate: str = "sum"
    min_sample: int = 3
    windowed: bool = True
    compute: Optional[Callable[..., Any]] = None
    description: str = ""
    min_denominator: float = 0.0
    sample_noun: str = "items"
    group: str = "activity"
    denominator_noun: str = "Claude cost"
    no_denominator_reason: Optional[str] = None


def missing_sources(conn: sqlite3.Connection, metric: Metric) -> List[str]:
    if metric.compute is None:
        return list(metric.needs)
    return [name for name in metric.needs if not _has_source(conn, name)]


def _has_source(conn: sqlite3.Connection, name: str) -> bool:
    return remembered(conn, ("source", name), lambda: conn.execute(SOURCE_PROBES[name]).fetchone() is not None)


def coverage_start(conn: sqlite3.Connection, source: str, history_days: int) -> Optional[str]:
    """The start of the window a source's first sync asked for, or None if it has no payloads."""
    first_fetch = remembered(conn, ("first_fetch", source), lambda: conn.execute(
        "SELECT MIN(fetched_at) AS first FROM raw_payload WHERE source = ?", (source,)).fetchone()["first"])
    if first_fetch is None:
        return None
    first = datetime.strptime(first_fetch, ISO_Z)
    return (first - timedelta(days=history_days)).strftime(ISO_Z)


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    ordered = sorted(values)
    if not ordered:
        return None
    rank = (len(ordered) - 1) * pct / 100.0
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 6)


def aggregate(values: Sequence[float], how: str) -> Optional[float]:
    if not values:
        return 0.0 if how == "sum" else None
    if how == "sum":
        return float(sum(values))
    if how == "median":
        return float(statistics.median(values))
    return float(sum(values)) / len(values)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def describe(conn: sqlite3.Connection, metric: Metric) -> Dict[str, Any]:
    missing = missing_sources(conn, metric)
    return {
        "name": metric.name,
        "label": metric.label,
        "unit": metric.unit,
        "kind": metric.kind,
        "needs": list(metric.needs),
        "better": metric.better,
        "description": metric.description,
        "group": metric.group,
        "status": "waiting" if missing else "ok",
        "missing": missing,
    }


def _group(obs: Observations, people: People, scope: Scope) -> Tuple[Dict[str, List[float]], List[float], int]:
    by_person: Dict[str, List[float]] = {}
    unmapped: List[float] = []
    unmapped_keys = 0
    for key, values in obs.by_actor.items():
        person = people.resolve(key)
        if person is None:
            unmapped.extend(values)
            unmapped_keys += 1
            continue
        if people.is_excluded(person):
            continue
        if scope.members is not None and person not in scope.members:
            continue
        by_person.setdefault(person, []).extend(values)
    return by_person, unmapped, unmapped_keys


def _per_person(conn, metric: Metric, scope: Scope, window: Window, people: People):
    current = metric.compute(conn, scope, window)
    by_person, unmapped, unmapped_keys = _group(current, people, scope)
    before: Dict[str, List[float]] = {}
    before_unmapped: List[float] = []
    if metric.windowed:
        before, before_unmapped, _ = _group(metric.compute(conn, scope, previous(window)), people, scope)
    person_ids = set(by_person) if scope.members is None else set(scope.members)
    rows: List[Dict[str, Any]] = []
    for person_id in person_ids:
        if people.is_excluded(person_id):
            continue
        values = by_person.get(person_id, [])
        value = aggregate(values, metric.aggregate)
        prior: Optional[float] = None
        if metric.windowed:
            prior = aggregate(before.get(person_id, []), metric.aggregate)
        trend = (value - prior) / prior if value is not None and prior else None
        rows.append({
            "person_id": person_id,
            "name": people.name(person_id),
            "value": _round(value),
            "sample": len(values),
            "previous": _round(prior),
            "trend": _round(trend),
            "ranked": value is not None and len(values) >= metric.min_sample,
            "rank": None,
            "confidence": None,
            "unranked_reason": None,
        })
    descending = metric.better != "lower"
    ranked = sorted(
        (row for row in rows if row["ranked"]),
        key=lambda row: (-row["value"] if descending else row["value"], row["name"].lower()),
    )
    for position, row in enumerate(ranked, 1):
        row["rank"] = position
    rest = sorted((row for row in rows if not row["ranked"]), key=lambda row: row["name"].lower())
    out = ranked + rest
    if unmapped:
        out.append({
            "person_id": None,
            "name": f"Unmapped ({unmapped_keys} account{'' if unmapped_keys == 1 else 's'})",
            "value": _round(aggregate(unmapped, metric.aggregate)),
            "sample": len(unmapped),
            "previous": None,
            "trend": None,
            "ranked": False,
            "rank": None,
            "confidence": None,
            "unranked_reason": None,
        })
    # The team total covers every row shown, including the Unmapped row.
    every = [value for values in by_person.values() for value in values] + unmapped
    team: Dict[str, Any] = {"value": _round(aggregate(every, metric.aggregate)), "sample": len(every)}
    team_value = aggregate(every, metric.aggregate)
    team_prior: Optional[float] = None
    if metric.windowed:
        earlier = [value for values in before.values() for value in values] + before_unmapped
        team_prior = aggregate(earlier, metric.aggregate)
    team_trend = (team_value - team_prior) / team_prior if team_value is not None and team_prior else None
    team["previous"] = _round(team_prior)
    team["trend"] = _round(team_trend)
    if metric.aggregate == "median":
        team["p85"] = _round(percentile(every, 85))
    return out, list(current.notes), team


def _round4(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 4)


def _ratio_parts(items: Sequence[Tuple[float, float, int]]) -> Tuple[float, float, int]:
    return sum(i[0] for i in items), sum(i[1] for i in items), sum(i[2] for i in items)


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    return None if denominator <= 0 else numerator / denominator


def _group_pairs(obs: Observations, people: People, scope: Scope):
    """Ratio observations by person. Ratio metrics are person-keyed, so unknown keys are dropped."""
    by_person: Dict[str, List[Tuple[float, float, int]]] = {}
    confidence: Dict[str, str] = {}
    unranked: Dict[str, str] = {}
    for key, items in obs.pairs.items():
        person = people.resolve(key)
        if person is None or people.is_excluded(person):
            continue
        if scope.members is not None and person not in scope.members:
            continue
        by_person.setdefault(person, []).extend(items)
        if key in obs.confidence:
            confidence[person] = obs.confidence[key]
        if key in obs.unranked:
            unranked[person] = obs.unranked[key]
    return by_person, confidence, unranked


def _per_person_ratio(conn, metric: Metric, scope: Scope, window: Window, people: People):
    current = metric.compute(conn, scope, window)
    by_person, confidence, unranked = _group_pairs(current, people, scope)
    before: Dict[str, List[Tuple[float, float, int]]] = {}
    before_unranked: Dict[str, str] = {}
    if metric.windowed:
        before, _, before_unranked = _group_pairs(metric.compute(conn, scope, previous(window)), people, scope)
    notes = list(current.notes)
    thin = False
    person_ids = set(by_person) if scope.members is None else set(scope.members)
    rows: List[Dict[str, Any]] = []
    team_num = team_den = 0.0
    team_n = 0
    for person_id in person_ids:
        if people.is_excluded(person_id):
            continue
        num, den, n = _ratio_parts(by_person.get(person_id, []))
        team_num, team_den, team_n = team_num + num, team_den + den, team_n + n
        value = _ratio(num, den)
        prior: Optional[float] = None
        if person_id in before:
            p_num, p_den, p_n = _ratio_parts(before[person_id])
            if p_n >= metric.min_sample and p_den >= metric.min_denominator and person_id not in before_unranked:
                prior = _ratio(p_num, p_den)
            else:
                thin = True
        trend = (value - prior) / prior if value is not None and prior else None
        reason = unranked.get(person_id)
        if reason is None and metric.no_denominator_reason and den <= 0:
            reason = metric.no_denominator_reason
        if reason is None and n < metric.min_sample:
            reason = f"fewer than {metric.min_sample} {metric.sample_noun}"
        if reason is None and den < metric.min_denominator:
            reason = f"under ${metric.min_denominator:.0f} of {metric.denominator_noun}"
        if reason is None and value is None:
            reason = "no cost to divide by"
        rows.append({
            "person_id": person_id, "name": people.name(person_id), "value": _round4(value),
            "numerator": round(num, 4), "denominator": round(den, 4), "sample": n,
            "previous": _round4(prior), "trend": _round4(trend), "ranked": reason is None, "rank": None,
            "confidence": confidence.get(person_id), "unranked_reason": reason,
        })
    descending = metric.better != "lower"
    ranked = sorted(
        (row for row in rows if row["ranked"]),
        key=lambda row: (-row["value"] if descending else row["value"], row["name"].lower()),
    )
    for position, row in enumerate(ranked, 1):
        row["rank"] = position
    rest = sorted((row for row in rows if not row["ranked"]), key=lambda row: row["name"].lower())
    if thin:
        notes.append("Trend hidden where the previous window is below the minimums (insufficient history).")
    team_value = _ratio(team_num, team_den)
    team_prior: Optional[float] = None
    if metric.windowed:
        earlier = [item for items in before.values() for item in items]
        team_prior = _ratio(*_ratio_parts(earlier)[:2])
    team_trend = (team_value - team_prior) / team_prior if team_value is not None and team_prior else None
    team = {"value": _round4(team_value), "sample": team_n, "numerator": round(team_num, 4),
            "denominator": round(team_den, 4), "previous": _round4(team_prior), "trend": _round4(team_trend)}
    return ranked + rest, notes, team


def _short_history(
    conn: sqlite3.Connection, metric: Metric, window: Window, history_days: int
) -> Optional[Tuple[str, str]]:
    """The needed source whose data starts latest, if that is after the previous window begins."""
    latest: Optional[Tuple[str, str]] = None
    for need in metric.needs:
        source = COVERAGE_SOURCES.get(need)
        starts = coverage_start(conn, source, history_days) if source else None
        if starts and (latest is None or starts > latest[1]):
            latest = (source, starts)
    if latest and previous(window).start < latest[1]:
        return latest
    return None


def run_metric(
    conn: sqlite3.Connection,
    metric: Metric,
    scope: Scope,
    window: Window,
    people: Optional[People] = None,
    *,
    history_days: int = 90,
) -> Dict[str, Any]:
    result = describe(conn, metric)
    result.update({"window": window.to_json(), "rows": [], "notes": [], "team": None})
    if result["status"] == "waiting":
        return result
    try:
        if metric.kind == PER_PERSON:
            per_person = _per_person_ratio if metric.aggregate == "ratio" else _per_person
            rows, notes, team = per_person(conn, metric, scope, window, people or People(conn))
        else:
            rows, notes = metric.compute(conn, scope, window)
            team = None
    except Exception as exc:  # one bad metric must not break the page
        result.update({"status": "error", "error": str(exc) or exc.__class__.__name__})
        return result
    if metric.kind == PER_PERSON and metric.windowed:
        short = _short_history(conn, metric, window, history_days)
        if short:
            source, starts = short
            for row in rows:
                row["previous"] = None
                row["trend"] = None
            team["previous"] = None
            team["trend"] = None
            notes = list(notes) + [f"Not enough history for a trend yet: {source} data starts {starts[:10]}."]
    result.update({"rows": rows, "notes": notes, "team": team})
    return result
