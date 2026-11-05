from datetime import date

from impact_seed import issue
from metrics_seed import TZ, person
from delivery_analysis.metrics import ai_weekly, explain

DAY0 = date(2026, 9, 19)
TODAY = date(2026, 11, 4)


def usage(conn, person_id, day, cost):
    conn.execute(
        "INSERT INTO token_usage (person_id, day, model, purpose, cost_usd, total_tokens, source, purpose_method, "
        "purpose_confidence) VALUES (?, ?, 'm', 'unclassified', ?, 10, 'claude', 'none', 'low')",
        (person_id, day, cost),
    )


def ann(conn):
    person(conn, "p-ann", "Ann Example", accounts=["acc-ann"])


def points_input(**extra):
    base = {"metric": "story_points_done", "blocks": [], "person": {}, "everyone": {}, "short_baseline": False}
    base.update(extra)
    return base


def test_no_claude_rows(conn):
    ann(conn)
    out = ai_weekly.weekly(conn, "p-ann", date(2026, 10, 5), date(2026, 10, 19), TZ)
    assert out["starts"] is None
    assert [w["week"] for w in out["weeks"]] == ["2026-10-05", "2026-10-12"]
    assert all(w["cost_usd"] == 0 and w["active_days"] == 0 and w["points"] == 0 for w in out["weeks"])


def test_weekly_cost_active_days_and_points(conn):
    ann(conn)
    usage(conn, "p-ann", "2026-07-23", 1.0)
    usage(conn, "p-ann", "2026-10-05", 30.25)
    usage(conn, "p-ann", "2026-10-06", 10.25)
    usage(conn, "p-ann", "2026-10-07", 0.0)
    usage(conn, "p-ann", "2026-10-12", 5.0)  # next week, outside the range
    issue(conn, "1", "acc-ann", resolved="2026-10-08T14:00:00Z", points=13)
    out = ai_weekly.weekly(conn, "p-ann", date(2026, 10, 5), date(2026, 10, 12), TZ)
    assert out == {"starts": "2026-07-23", "weeks": [
        {"week": "2026-10-05", "cost_usd": 40.5, "active_days": 2, "points": 13.0}]}


def test_empty_week_between_busy_weeks_is_present(conn):
    ann(conn)
    usage(conn, "p-ann", "2026-10-05", 2.0)
    usage(conn, "p-ann", "2026-10-19", 3.0)
    weeks = ai_weekly.weekly(conn, "p-ann", date(2026, 10, 5), date(2026, 10, 26), TZ)["weeks"]
    assert [(w["week"], w["cost_usd"], w["active_days"]) for w in weeks] == [
        ("2026-10-05", 2.0, 1), ("2026-10-12", 0.0, 0), ("2026-10-19", 3.0, 1)]


def seed_after(conn, big):
    ann(conn)
    issue(conn, "1", "acc-ann", resolved="2026-09-25T14:00:00Z", points=big)
    issue(conn, "2", "acc-ann", resolved="2026-10-10T14:00:00Z", points=2)
    issue(conn, "3", "acc-ann", resolved="2026-10-12T14:00:00Z", points=2)
    issue(conn, "4", "acc-ann", resolved="2026-10-14T14:00:00Z", points=2)
    issue(conn, "5", "acc-ann", resolved="2026-10-16T14:00:00Z", points=2)


def test_one_ticket_share(conn):
    seed_after(conn, 8)  # 8 of 16 points
    notes = explain.explain(conn, "p-ann", DAY0, TODAY, points_input())
    assert any("MD-1" in n and "50%" in n for n in notes)
    assert not any("MD-2" in n for n in notes)


def test_no_ticket_named_when_none_is_over_40_percent(conn):
    seed_after(conn, 2)
    for i in range(6, 10):
        issue(conn, str(i), "acc-ann", resolved=f"2026-10-{i + 10}T14:00:00Z", points=2)
    notes = explain.explain(conn, "p-ann", DAY0, TODAY, points_input())
    assert not any(" alone is " in n for n in notes)


def test_lump_note(conn):
    ann(conn)
    issue(conn, "1", "acc-ann", resolved="2026-09-25T14:00:00Z", points=3)
    issue(conn, "2", "acc-ann", resolved="2026-09-25T15:00:00Z", points=3)
    for i, day in enumerate(["01", "08", "12", "16", "20"], 3):
        issue(conn, str(i), "acc-ann", resolved=f"2026-10-{day}T14:00:00Z", points=1)
    notes = explain.explain(conn, "p-ann", DAY0, TODAY, points_input())
    assert any(n.startswith("A lump: 2026-09-25") and "Days 1-30" in n for n in notes)


def test_no_points_means_only_the_closing_note(conn):
    ann(conn)
    notes = explain.explain(conn, "p-ann", DAY0, TODAY, points_input())
    assert notes == ["Not visible in the data: mentoring, tool choice, whether AI suggestions were reviewed."]


def test_zero_before_median_gives_no_team_note(conn):
    ann(conn)
    every = {"before": {"median": 0.0}, "after": {"median": 5.0}}
    notes = explain.explain(conn, "p-ann", DAY0, TODAY, points_input(everyone=every))
    assert not any("Team-wide" in n for n in notes)


def test_short_baseline_note(conn):
    ann(conn)
    notes = explain.explain(conn, "p-ann", DAY0, TODAY, points_input(short_baseline=True))
    assert notes[0].startswith("Short baseline")
    assert notes[-1].startswith("Not visible in the data")


def test_team_wide_note(conn):
    ann(conn)
    rose = {"before": {"median": 10.0}, "after": {"median": 12.0}}
    flat = {"before": {"median": 10.0}, "after": {"median": 11.9}}
    assert any("Team-wide" in n and "20%" in n for n in explain.explain(conn, "p-ann", DAY0, TODAY, points_input(everyone=rose)))
    assert not any("Team-wide" in n for n in explain.explain(conn, "p-ann", DAY0, TODAY, points_input(everyone=flat)))
