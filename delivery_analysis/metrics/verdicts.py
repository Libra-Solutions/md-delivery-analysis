"""Verdict words per window item: Hit, Partly, Not evidenced or Cannot see."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

HIT, PARTLY, NOT_EVIDENCED, CANNOT_SEE = "Hit", "Partly", "Not evidenced", "Cannot see"

TESTS_SHARE = 0.70
TESTS_PARTLY = 0.50
DURABILITY = 0.95
DURABILITY_PARTLY = 0.90
COMMENT_SLACK = 0.2
COMMENT_PARTLY_SLACK = 0.5
INLINE_MID = 3
INLINE_SENIOR_LATER = 5
NEVER_SEEN = ("Mentoring and pairing", "Tool choice", "AI suggestions reviewed")


def _num(facts: Dict[str, Any], key: str) -> Optional[float]:
    value = facts.get(key)
    return None if value is None else float(value)


def _row(item: str, verdict: str, value: Optional[float], threshold: str) -> Dict[str, Any]:
    return {"item": item, "verdict": verdict, "value": value, "threshold": threshold}


def _fmt(number: float) -> str:
    return f"{number:g}" if number != int(number) else str(int(number))


def _later_window(label: str) -> bool:
    """True for Days 1-60 and Days 1-90 (the windows past Day 30)."""
    return label.strip() != "Days 1-30"


def _pace(facts: Dict[str, Any]) -> Dict[str, Any]:
    pace, before, median = (_num(facts, k) for k in ("pace_per30", "before_median", "median_per30"))
    rule = "at or above own before median {b} and the median of everyone {m}".format(
        b="?" if before is None else _fmt(before), m="?" if median is None else _fmt(median))
    if pace is None or (before is None and median is None):
        return _row("Pace", CANNOT_SEE, pace, rule)
    beat = [pace >= x for x in (before, median) if x is not None]
    if all(beat) and before is not None and median is not None:
        return _row("Pace", HIT, pace, rule)
    return _row("Pace", PARTLY if any(beat) else NOT_EVIDENCED, pace, rule)


def _share(item: str, value: Optional[float], hit: float, partly: float, rule: str) -> Dict[str, Any]:
    if value is None:
        return _row(item, CANNOT_SEE, None, rule)
    verdict = HIT if value >= hit else PARTLY if value >= partly else NOT_EVIDENCED
    return _row(item, verdict, value, rule)


def _comments(facts: Dict[str, Any]) -> Dict[str, Any]:
    value, before = _num(facts, "comments_per_pr"), _num(facts, "before_comments_per_pr")
    if before is None:
        return _row("Review comments per PR", CANNOT_SEE, value, "at most own before level plus 0.2")
    rule = f"at most own before level {_fmt(before)} plus 0.2"
    if value is None:
        return _row("Review comments per PR", CANNOT_SEE, None, rule)
    limit = round(before + COMMENT_SLACK, 9)
    verdict = HIT if value <= limit else PARTLY if value <= before + COMMENT_PARTLY_SLACK else NOT_EVIDENCED
    return _row("Review comments per PR", verdict, value, rule)


def verdicts(level: str, label: str, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    facts = facts or {}
    later = _later_window(label)
    inline_need = INLINE_SENIOR_LATER if (level == "Senior" and later) else INLINE_MID
    rows = [
        _pace(facts),
        _share("Tests in PRs", _num(facts, "tests_share"), TESTS_SHARE, TESTS_PARTLY,
               "at least 70% of PRs touch tests"),
        _share("Durability", _num(facts, "durability"), DURABILITY, DURABILITY_PARTLY, "at least 0.95"),
        _comments(facts),
    ]
    inline = _num(facts, "inline_comments")
    inline_rule = f"at least {inline_need} inline comments given"
    if inline is None:
        rows.append(_row("Inline comments given", CANNOT_SEE, None, inline_rule))
    else:
        verdict = HIT if inline >= inline_need else PARTLY if inline >= 1 else NOT_EVIDENCED
        rows.append(_row("Inline comments given", verdict, inline, inline_rule))
    if later:
        big = _num(facts, "big_tickets")
        rule = "at least one ticket of 8 points or more"
        rows.append(_row("Big ticket (8+ points)", CANNOT_SEE if big is None else
                         (HIT if big >= 1 else NOT_EVIDENCED), big, rule))
    for item in NEVER_SEEN:
        rows.append(_row(item, CANNOT_SEE, None, "the app has no way to see this"))
    return rows
