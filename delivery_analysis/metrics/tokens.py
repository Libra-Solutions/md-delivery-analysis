"""Claude cost metrics: impact per token (cost proxy), cost, unattributed share, ask and generate."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from delivery_analysis.metrics.delivered import DELIVERED_AT_SQL
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window, local_day, week_start
from delivery_analysis.store.db import all_rows
from delivery_analysis.tokens.config import DEFAULT_CONFIG, AttributionConfig

TicketKey = Tuple[str, str]
COVERAGE_NOTE = ("Claude cost covers Claude Code usage by Claude Enterprise users; chat and other products, "
                 "direct API keys, Bedrock and Vertex are not included.")
PROXY_NOTE = "Ask and generate are a coarse proxy (v1) from accepted edits: low confidence, context only."
ORDER = {"high": 0, "medium": 1, "low": 2}


def window_days(window: Window) -> Tuple[str, str]:
    """The window's local dates as UTC-day strings: first inclusive, end exclusive."""
    first = window.first_day
    return first.isoformat(), (first + timedelta(days=window.days)).isoformat()


def _key(person_id: str) -> str:
    return f"person:{person_id}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


@dataclass
class Cohort:
    """Tickets completed in a window, with each person's attributed cost (sub-tasks rolled up) and credit."""

    tickets: Dict[TicketKey, Dict[str, Any]] = field(default_factory=dict)
    cost: Dict[Tuple[TicketKey, str], float] = field(default_factory=dict)
    levels: Dict[Tuple[TicketKey, str], Dict[str, float]] = field(default_factory=dict)
    credit: Dict[TicketKey, Dict[str, float]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def people(self, ticket: TicketKey) -> List[str]:
        return sorted(set(self.credit.get(ticket, {})) | {p for (t, p) in self.cost if t == ticket})


def load_cohort(conn: sqlite3.Connection, window: Window) -> Cohort:
    out = Cohort()
    start_row = conn.execute("SELECT MIN(day) AS d FROM token_attribution").fetchone()
    coverage = start_row["d"] if start_row else None
    no_points = early = 0
    for row in conn.execute(
        "SELECT w.source, w.source_id, w.key, w.type, w.story_points, w.started_at, "
        + DELIVERED_AT_SQL + " AS resolved_at "
        "FROM work_item w WHERE w.source = 'jira' "
        "AND " + DELIVERED_AT_SQL + " >= ? AND " + DELIVERED_AT_SQL + " < ? AND EXISTS (SELECT 1 FROM property p "
        "WHERE p.record_kind = 'work_item' AND p.record_id = w.source_id AND p.name = 'counts_for_impact' "
        "AND p.value = '1')",
        (window.start, window.end),
    ):
        if row["story_points"] is None:
            no_points += 1
            continue
        if coverage and row["started_at"] and row["started_at"][:10] < coverage:
            early += 1
            continue
        out.tickets[(row["source"], row["source_id"])] = {
            "issue_key": row["key"], "type": row["type"], "points": float(row["story_points"]),
            "resolved_at": row["resolved_at"],
        }
    if no_points:
        out.notes.append(f"{_plural(no_points, 'completed ticket')} without story points left out.")
    if early:
        out.notes.append(f"{_plural(early, 'completed ticket')} started before Claude cost coverage "
                         f"({coverage}) left out.")
    if not out.tickets:
        return out
    owner: Dict[str, TicketKey] = {key[1]: key for key in out.tickets}
    for row in all_rows(
        conn, "SELECT from_id, to_id FROM link WHERE kind = 'parent' AND from_kind = 'work_item' AND to_kind = 'work_item'"
    ):
        parent = ("jira", row["to_id"])
        if parent in out.tickets:
            owner.setdefault(row["from_id"], parent)
    for row in all_rows(
        conn, "SELECT person_id, work_item_id, cost_usd, confidence FROM token_attribution "
        "WHERE work_item_source = 'jira' AND work_item_id != ''"
    ):
        ticket = owner.get(row["work_item_id"])
        if ticket is None:
            continue
        key = (ticket, row["person_id"])
        out.cost[key] = out.cost.get(key, 0.0) + row["cost_usd"]
        levels = out.levels.setdefault(key, {})
        level = row["confidence"] or "low"
        levels[level] = levels.get(level, 0.0) + row["cost_usd"]
    for row in all_rows(conn, "SELECT work_item_source, work_item_id, person_id, share FROM ticket_credit"):
        ticket = (row["work_item_source"], row["work_item_id"])
        if ticket in out.tickets:
            out.credit.setdefault(ticket, {})[row["person_id"]] = row["share"]
    return out


def _day_totals(conn: sqlite3.Connection, window: Window) -> Dict[str, Tuple[float, float]]:
    """Per person over the window's attributed days: (unattributed cost, total cost)."""
    first, end = window_days(window)
    return {
        row["person_id"]: (row["un"] or 0.0, row["total"] or 0.0)
        for row in conn.execute(
            "SELECT person_id, SUM(CASE WHEN work_item_id = '' THEN cost_usd ELSE 0 END) AS un, "
            "SUM(cost_usd) AS total FROM token_attribution WHERE day >= ? AND day < ? GROUP BY person_id",
            (first, end),
        )
    }


def _marker(levels: Dict[str, float], unattributed: float, tickets: int, config: AttributionConfig) -> str:
    total = sum(levels.values())
    good = (levels.get("high", 0.0) + levels.get("medium", 0.0)) / total if total else 0.0
    if tickets >= config.high_min_tickets and good >= config.high_share and unattributed <= config.high_max_unattributed:
        return "high"
    if tickets >= config.min_tickets and good >= config.medium_share and unattributed <= config.medium_max_unattributed:
        return "medium"
    return "low"


def _cohort_pairs(conn: sqlite3.Connection, window: Window, all_in: bool, config: AttributionConfig) -> Observations:
    cohort = load_cohort(conn, window)
    obs = Observations(notes=list(cohort.notes) + [COVERAGE_NOTE])
    totals = _day_totals(conn, window)
    levels: Dict[str, Dict[str, float]] = {}
    tickets: Dict[str, int] = {}
    for ticket, info in cohort.tickets.items():
        for person in cohort.people(ticket):
            share = cohort.credit.get(ticket, {}).get(person, 0.0)
            cost = 0.0 if all_in else cohort.cost.get((ticket, person), 0.0)
            if share <= 0:
                # Cost without credited points still counts as spend, but not as a completed ticket.
                obs.add_pair(_key(person), 0.0, cost, sample=0)
                continue
            obs.add_pair(_key(person), info["points"] * share, cost)
            tickets[person] = tickets.get(person, 0) + 1
            mine = levels.setdefault(person, {})
            for level, value in cohort.levels.get((ticket, person), {}).items():
                mine[level] = mine.get(level, 0.0) + value
    for person, count in tickets.items():
        unattributed, total = totals.get(person, (0.0, 0.0))
        if all_in:
            obs.add_pair(_key(person), 0.0, total, sample=0)
        share = unattributed / total if total else 0.0
        obs.confidence[_key(person)] = _marker(levels.get(person, {}), share, count, config)
        if share > config.unranked_max_unattributed:
            obs.unranked[_key(person)] = f"over {config.unranked_max_unattributed:.0%} of Claude cost unattributed"
    return obs


def story_points_per_dollar(conn, scope: Scope, window: Window, config: AttributionConfig = DEFAULT_CONFIG) -> Observations:
    return _cohort_pairs(conn, window, False, config)


def story_points_per_dollar_all_in(conn, scope: Scope, window: Window,
                                   config: AttributionConfig = DEFAULT_CONFIG) -> Observations:
    return _cohort_pairs(conn, window, True, config)


def _weeks(window: Window) -> List[date]:
    out: List[date] = []
    week = week_start(window.first_day)
    last = window.first_day + timedelta(days=window.days - 1)
    while week <= last:
        out.append(week)
        week += timedelta(days=7)
    return out


def story_points_per_dollar_weekly(conn, scope: Scope, window: Window,
                                   config: AttributionConfig = DEFAULT_CONFIG):
    cohort = load_cohort(conn, window)
    cells: Dict[date, List[float]] = {}
    for ticket, info in cohort.tickets.items():
        people = [p for p in cohort.people(ticket) if scope.members is None or p in scope.members]
        if not people:
            continue
        cell = cells.setdefault(week_start(local_day(info["resolved_at"], window.tz)), [0.0, 0.0, 0])
        cell[0] += info["points"] * sum(cohort.credit.get(ticket, {}).get(p, 0.0) for p in people)
        cell[1] += sum(cohort.cost.get((ticket, p), 0.0) for p in people)
        cell[2] += 1
    rows = []
    for week in _weeks(window):
        points, cost, count = cells.get(week, [0.0, 0.0, 0])
        value = round(points / cost, 4) if count >= config.min_tickets and cost > 0 else None
        rows.append({"week": week.isoformat(), "points": round(points, 2), "cost_usd": round(cost, 2),
                     "tickets": int(count), "value": value})
    notes = list(cohort.notes) + [
        f"Weeks with fewer than {config.min_tickets} completed tickets show no value.", COVERAGE_NOTE]
    return rows, notes


def cost_spent(conn, scope: Scope, window: Window) -> Observations:
    first, end = window_days(window)
    obs = Observations(notes=[COVERAGE_NOTE])
    for row in conn.execute(
        "SELECT actor_type, actor, day, SUM(cost_usd) AS cost FROM claude_usage_day "
        "WHERE day >= ? AND day < ? GROUP BY actor_type, actor, day ORDER BY day",
        (first, end),
    ):
        obs.add(f"{row['actor_type']}:{row['actor']}", round(row["cost"], 6))
    return obs


def unattributed_cost_share(conn, scope: Scope, window: Window) -> Observations:
    first, end = window_days(window)
    obs = Observations(notes=["Share of each person's Claude cost on attributed days that no ticket received."])
    for row in conn.execute(
        "SELECT person_id, day, SUM(CASE WHEN work_item_id = '' THEN cost_usd ELSE 0 END) AS un, "
        "SUM(cost_usd) AS total FROM token_attribution WHERE day >= ? AND day < ? GROUP BY person_id, day",
        (first, end),
    ):
        obs.add_pair(_key(row["person_id"]), row["un"] or 0.0, row["total"] or 0.0)
    return obs


def ask_generate_ratio(conn, scope: Scope, window: Window) -> Observations:
    first, end = window_days(window)
    obs = Observations(notes=[PROXY_NOTE])
    for row in conn.execute(
        "SELECT person_id, day, SUM(CASE WHEN purpose = 'ask' THEN cost_usd ELSE 0 END) AS ask, "
        "SUM(CASE WHEN purpose = 'generate' THEN cost_usd ELSE 0 END) AS gen FROM token_usage "
        "WHERE day >= ? AND day < ? AND purpose IN ('ask', 'generate') GROUP BY person_id, day",
        (first, end),
    ):
        obs.add_pair(_key(row["person_id"]), row["ask"] or 0.0, row["gen"] or 0.0)
    return obs


def cost_by_purpose_weekly(conn, scope: Scope, window: Window):
    first, end = window_days(window)
    cells: Dict[date, Dict[str, float]] = {}
    for row in conn.execute(
        "SELECT person_id, day, purpose, SUM(cost_usd) AS cost FROM token_usage "
        "WHERE day >= ? AND day < ? GROUP BY person_id, day, purpose",
        (first, end),
    ):
        if scope.members is not None and row["person_id"] not in scope.members:
            continue
        cell = cells.setdefault(week_start(date.fromisoformat(row["day"])), {})
        cell[row["purpose"]] = cell.get(row["purpose"], 0.0) + row["cost"]
    rows = []
    for week in _weeks(window):
        cell = cells.get(week, {})
        rows.append({"week": week.isoformat(), "ask": round(cell.get("ask", 0.0), 2),
                     "generate": round(cell.get("generate", 0.0), 2),
                     "unclassified": round(cell.get("unclassified", 0.0), 2)})
    return rows, [PROXY_NOTE, "Weeks are UTC weeks; people without a mapping are not included.", COVERAGE_NOTE]
