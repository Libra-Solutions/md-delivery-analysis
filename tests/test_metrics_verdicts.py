from delivery_analysis.metrics.verdicts import verdicts

FACTS = {"pace_per30": 46.0, "before_median": 24, "median_per30": 24, "tests_share": 0.8,
         "durability": 0.97, "comments_per_pr": 1.0, "before_comments_per_pr": 1.0,
         "inline_comments": 4, "big_tickets": 1}


def pick(rows, item):
    return next(r for r in rows if r["item"] == item)


def test_pace_hit():
    assert verdicts("Mid", "Days 1-30", FACTS)[0] == {
        "item": "Pace", "verdict": "Hit", "value": 46.0,
        "threshold": "at or above own before median 24 and the median of everyone 24"}


def test_pace_partly():
    rows = verdicts("Mid", "Days 1-30", {**FACTS, "pace_per30": 20, "before_median": 18})
    assert rows[0]["verdict"] == "Partly"


def test_pace_not_evidenced():
    assert verdicts("Mid", "Days 1-30", {**FACTS, "pace_per30": 10})[0]["verdict"] == "Not evidenced"


def test_tests_threshold():
    assert pick(verdicts("Mid", "Days 1-30", {**FACTS, "tests_share": 0.69}), "Tests in PRs")["verdict"] == "Partly"
    assert pick(verdicts("Mid", "Days 1-30", {**FACTS, "tests_share": 0.70}), "Tests in PRs")["verdict"] == "Hit"


def test_comments_limit():
    f = {**FACTS, "before_comments_per_pr": 1.0}
    assert pick(verdicts("Mid", "Days 1-30", {**f, "comments_per_pr": 1.2}), "Review comments per PR")["verdict"] == "Hit"
    assert pick(verdicts("Mid", "Days 1-30", {**f, "comments_per_pr": 1.3}), "Review comments per PR")["verdict"] == "Partly"
    assert pick(verdicts("Mid", "Days 1-30", {**f, "comments_per_pr": 2.0}), "Review comments per PR")["verdict"] == "Not evidenced"


def test_senior_day60_inline():
    f = {**FACTS, "inline_comments": 4}
    assert pick(verdicts("Senior", "Days 1-30", f), "Inline comments given")["verdict"] == "Hit"
    assert pick(verdicts("Senior", "Days 1-60", f), "Inline comments given")["verdict"] == "Partly"
    assert pick(verdicts("Senior", "Days 1-60", {**f, "inline_comments": 5}), "Inline comments given")["verdict"] == "Hit"
    assert pick(verdicts("Mid", "Days 1-60", f), "Inline comments given")["verdict"] == "Hit"


def test_big_ticket_day60():
    assert not [r for r in verdicts("Mid", "Days 1-30", FACTS) if r["item"].startswith("Big ticket")]
    assert pick(verdicts("Mid", "Days 1-60", FACTS), "Big ticket (8+ points)")["verdict"] == "Hit"
    assert pick(verdicts("Mid", "Days 1-60", {**FACTS, "big_tickets": 0}), "Big ticket (8+ points)")["verdict"] == "Not evidenced"


def test_missing_fact_cannot_see():
    rows = verdicts("Mid", "Days 1-60", {k: None for k in FACTS})
    assert all(r["verdict"] == "Cannot see" for r in rows)
    assert verdicts("Mid", "Days 1-30", {})[0]["verdict"] == "Cannot see"


def test_always_cannot_see():
    tail = verdicts("Senior", "Days 1-90", FACTS)[-3:]
    assert [r["item"] for r in tail] == ["Mentoring and pairing", "Tool choice", "AI suggestions reviewed"]
    assert all(r["verdict"] == "Cannot see" for r in tail)
