"""Plain-language caveats for one person's points around Day 0 (T12).

The signature carries no time zone, so delivery days are the UTC dates of the delivery timestamps."""

from __future__ import annotations

from datetime import date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from delivery_analysis.metrics.credit import credit_for
from delivery_analysis.metrics.people import People
from delivery_analysis.metrics.window import make_window

TICKET_SHARE = 0.40
DAY_SHARE = 0.30
TEAM_RISE = 1.2
BLOCK_DAYS = 30
BLOCKS = 3
CLOSING = "Not visible in the data: mentoring, tool choice, whether AI suggestions were reviewed."


def _earned(conn, person_id: str, first: date, last: date) -> List[Tuple[str, str, float]]:
    """(ticket key, delivery day, points) for this person's share of tickets delivered in [first, last]."""
    window = make_window("custom", timezone.utc, last, start=first.isoformat(), end=last.isoformat())
    credit = credit_for(conn, window)
    people = People(conn)
    out = []
    for row in credit.issues:
        if row["story_points"] is None:
            continue
        for actor, share in (credit.shares.get(row["source_id"]) or {}).items():
            if share and people.resolve(actor) == person_id:
                out.append((row["key"], row["resolved_at"][:10], float(row["story_points"]) * share))
    return out


def _rise(points: Dict[str, Any]) -> Optional[float]:
    everyone = points.get("everyone") or {}
    before = (everyone.get("before") or {}).get("median")
    after = (everyone.get("after") or {}).get("median")
    if not before or after is None or before <= 0:
        return None
    return after / before


def explain(conn, person_id: str, day0: date, today: date, points: dict) -> list:
    notes: List[str] = []
    if points.get("short_baseline"):
        notes.append("Short baseline: fewer than 6 blocks of history before Day 0, so the before figures are a weak comparison.")
    rise = _rise(points)
    if rise is not None and rise >= TEAM_RISE:
        notes.append(
            f"Team-wide change: everyone's median rose {round((rise - 1) * 100)}% after Day 0, "
            "so part of this person's change is not specific to them."
        )
    if today >= day0:
        earned = _earned(conn, person_id, day0, today)
        total = sum(value for _, _, value in earned)
        if total > 0:
            by_ticket: Dict[str, float] = {}
            for key, _, value in earned:
                by_ticket[key] = by_ticket.get(key, 0.0) + value
            for key, value in sorted(by_ticket.items()):
                if value / total > TICKET_SHARE:
                    notes.append(f"{key} alone is {round(value / total * 100)}% of the points since Day 0.")
            for block in range(BLOCKS):
                first = day0 + timedelta(days=BLOCK_DAYS * block)
                last = min(first + timedelta(days=BLOCK_DAYS - 1), today)
                if first > today:
                    break
                by_day: Dict[str, float] = {}
                for _, day, value in earned:
                    if first.isoformat() <= day <= last.isoformat():
                        by_day[day] = by_day.get(day, 0.0) + value
                window_total = sum(by_day.values())
                if window_total <= 0:
                    continue
                for day, value in sorted(by_day.items()):
                    if value / window_total >= DAY_SHARE:
                        lo, hi = BLOCK_DAYS * block + 1, BLOCK_DAYS * (block + 1)
                        notes.append(f"A lump: {day} holds {round(value / window_total * 100)}% of the points in Days {lo}-{hi}.")
    notes.append(CLOSING)
    return notes
