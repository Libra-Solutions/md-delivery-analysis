"""Block math: 30-day block dates, summaries and pro-rating around Day 0."""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Dict, List, Optional

BLOCK_DAYS = 30


def day_reached(day0: date, today: date) -> int:
    """Days since Day 0 (negative before it)."""
    return (today - day0).days


def block_dates(day0: date, today: date, back: int = 12) -> List[Dict[str, object]]:
    """Blocks from `back` before Day 0 to the one holding today. Block 0 starts at Day 0.

    Only blocks on or before today appear; the last one is partial while it is running.
    """
    out: List[Dict[str, object]] = []
    for index in range(-back, 0):
        out.append({"index": index, "first": (day0 + timedelta(days=BLOCK_DAYS * index)).isoformat(),
                    "days": BLOCK_DAYS, "partial": False})
    index = 0
    while True:
        start = day0 + timedelta(days=BLOCK_DAYS * index)
        if start > today:
            break
        seen = (today - start).days + 1
        full = seen >= BLOCK_DAYS
        out.append({"index": index, "first": start.isoformat(),
                    "days": BLOCK_DAYS if full else seen, "partial": not full})
        index += 1
    # Blocks that end after today (day0 in the future) are not complete either.
    return [b for b in out if date.fromisoformat(str(b["first"])) <= today]


def summarize(values: list) -> Dict[str, Optional[float]]:
    if not values:
        return {"median": None, "average": None, "low": None, "high": None, "count": 0}
    nums = [float(v) for v in values]
    return {"median": float(median(nums)), "average": sum(nums) / len(nums),
            "low": min(nums), "high": max(nums), "count": len(nums)}


def prorate(value: float, days: int, full: int = BLOCK_DAYS) -> float:
    if days <= 0:
        raise ValueError("days must be positive")
    return value * full / days
