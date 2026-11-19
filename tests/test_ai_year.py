from datetime import date

from delivery_analysis.metrics import ai_year
from test_app_api import make


def test_month_blocks_twelve_months_ending_with_the_running_one():
    months = ai_year.month_blocks(date(2026, 11, 5), date(2026, 7, 23))
    assert len(months) == 12
    assert months[0]["first"] == "2025-12-01" and months[0]["index"] == -7
    assert months[-1] == {"index": 4, "first": "2026-11-01", "days": 5, "month_days": 30, "partial": True}
    assert [m["index"] for m in months if m["first"] == "2026-07-01"] == [0]
    assert months[2]["first"] == "2026-02-01" and months[2]["days"] == 28 and not months[2]["partial"]


def test_month_blocks_without_ai_start_are_all_before():
    months = ai_year.month_blocks(date(2026, 1, 31), None)
    assert [m["index"] for m in months] == list(range(-12, 0))
    assert months[0]["first"] == "2025-02-01" and months[-1]["partial"] is False


def test_periods_split_at_the_ai_start():
    today = date(2026, 11, 5)
    before, since = ai_year.periods(today, date(2026, 7, 23))
    assert (before["label"], before["first"], before["days"]) == ("Before AI", date(2025, 12, 1), 234)
    assert (since["label"], since["first"], since["days"]) == ("Since AI", date(2026, 7, 23), 106)
    assert [p["label"] for p in ai_year.periods(today, None)] == ["Last 12 months"]
    # An AI start before the twelve months: everything shown is since AI.
    assert [p["label"] for p in ai_year.periods(today, date(2024, 1, 1))] == ["Since AI"]


def test_effect_compares_the_person_with_the_group():
    own = {"before": {"median": 10.0, "average": 12.0}, "after": {"median": 15.0, "average": 18.0}}
    group = {"before": {"median": 10.0, "average": 10.0}, "after": {"median": 12.0, "average": 11.0}}
    out = ai_year.effect(own, group)
    assert out["person"]["median"] == {"change": 5.0, "ratio": 1.5}
    assert out["group"]["median"] == {"change": 2.0, "ratio": 1.2}
    assert out["vs_group"] == 0.3
    empty = ai_year.effect({"before": {}, "after": {"median": 1.0}}, group)
    assert empty["person"]["median"] == {"change": None, "ratio": None} and empty["vs_group"] is None
    assert ai_year.effect({"before": {"median": 0.0}, "after": {"median": 3.0}}, group)["person"]["median"]["ratio"] is None


class _Metric:
    def __init__(self, aggregate):
        self.aggregate = aggregate


def test_is_hole_only_when_nobody_has_any():
    from delivery_analysis.metrics import uplift

    total = _Metric("sum")
    assert uplift.is_hole(total, {"a": 0.0, "b": 0.0}, None, "a") is True
    assert uplift.is_hole(total, {"a": 0.0, "b": 2.0}, None, "a") is False  # a real zero month for a
    assert uplift.is_hole(total, {"a": 0.0, "b": 2.0}, ["a"], "a") is True  # the chosen group has none
    assert uplift.is_hole(total, {"a": None, "b": None}, None, "a") is False  # nothing ran: not a hole
    assert uplift.is_hole(_Metric("ratio"), {"a": 0.0, "b": 0.0}, None, "a") is False


def test_months_nobody_has_data_for_are_no_data_not_zero(tmp_path, monkeypatch):
    from delivery_analysis.metrics import uplift
    from delivery_analysis.store import db

    _client, path, *_ = make(tmp_path)
    conn = db.connect(path)

    def fake_values(conn, metric, scope, people, population, tz, today, first, days, person_id):
        if first < date(2026, 7, 1):
            return {pid: 0.0 for pid in population}  # the repositories do not reach back this far
        return {pid: (6.0 if pid == "p-ann" else 2.0) for pid in population}

    monkeypatch.setattr(uplift, "_values", fake_values)
    graph = ai_year.person_months(conn, "p-ann", uplift.People(conn).all and __import__(
        "delivery_analysis.metrics.people", fromlist=["team_scope"]).team_scope(conn, None),
        "prs_merged", date(2026, 7, 23), date(2026, 11, 5), "UTC")
    conn.close()
    holes = [b["start"] for b in graph["blocks"] if b["no_data"]]
    assert holes == ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert all(b["value"] is None and b["median"] is None for b in graph["blocks"] if b["no_data"])
    assert graph["person"]["before"]["count"] == 0  # no zeros dragging the baseline down
    assert graph["person"]["after"]["median"] == 6.0 and graph["effect"]["person"]["median"]["change"] is None
    assert graph["short_baseline"] is True


def _claude(conn, person_id, day, cost):
    conn.execute(
        "INSERT INTO token_usage (person_id, day, model, purpose, cost_usd, source, purpose_method, purpose_confidence) "
        "VALUES (?, ?, 'm', 'unclassified', ?, 'claude_code', 'none', 'low')", (person_id, day, cost))
    conn.execute(
        "INSERT OR IGNORE INTO claude_usage_day (source, day, actor_type, actor, model, cost_usd, fetched_at) "
        "VALUES ('claude_code', ?, 'email', 'someone@example.example', 'm', ?, ?)", (day, cost, day))
    conn.commit()


def test_ai_start_is_the_first_day_with_cost(tmp_path):
    from delivery_analysis.store import db

    _client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    _claude(conn, "p-ann", "2026-08-03", 0.0)
    _claude(conn, "p-ann", "2026-08-04", 1.5)
    _claude(conn, "p-ann", "2026-09-01", 2.0)
    assert ai_year.ai_start(conn, "p-ann") == date(2026, 8, 4)
    assert ai_year.ai_start(conn, "p-bob") is None
    assert ai_year.claude_data_start(conn) == date(2026, 8, 4)
    conn.close()


def test_year_api_real_layer(tmp_path):
    from delivery_analysis.store import cohort, db

    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    cohort.set_member(conn, "p-ann", "Senior", "2026-09-19")
    cohort.set_member(conn, "p-bob", "Mid", "2026-09-19")
    _claude(conn, "p-ann", "2026-08-04", 1.5)
    conn.close()

    people = client.get("/api/uplift/year/people").json()
    by_id = {p["person_id"]: p for p in people["people"]}
    assert by_id["p-ann"]["ai_start"] == "2026-08-04" and by_id["p-ann"]["at_data_start"] is True
    assert by_id["p-bob"]["ai_start"] is None

    body = client.get("/api/uplift/year/person/p-ann", params={"compare": "team:t1"})
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["compare"]["size"] == 2 and data["level"] == "Senior"
    assert set(data["graphs"]) == {"story_points_done", "prs_merged", "reviews_given"}
    graph = data["graphs"]["prs_merged"]
    assert len(graph["blocks"]) == 12 and "vs_group" in graph["effect"]
    labels = [p["label"] for p in data["expectations"]]
    assert labels[-1] == "Since AI"
    items = {i["item"] for i in data["expectations"][-1]["items"]}
    assert {"Pace", "Tests in PRs", "Durability", "Big ticket (8+ points)"} <= items
    assert any("may have started earlier" in n for n in data["notes"])

    unknown = client.get("/api/uplift/year/person/p-bob").json()
    assert [p["label"] for p in unknown["expectations"]] == ["Last 12 months"]
    assert unknown["ai_start"] is None and "No Claude use" in unknown["notes"][0]
    assert client.get("/api/uplift/year/person/p-nobody").status_code == 404


def test_year_page_served(tmp_path):
    client, *_ = make(tmp_path)
    page = client.get("/ai-year")
    assert page.status_code == 200 and "pages/ai-year.js" in page.text


def test_running_month_shows_the_actual_value_and_stays_out_of_the_medians(tmp_path, monkeypatch):
    from delivery_analysis.metrics import uplift
    from delivery_analysis.metrics.people import team_scope
    from delivery_analysis.store import db

    _client, path, *_ = make(tmp_path)
    conn = db.connect(path)

    def fake_values(conn, metric, scope, people, population, tz, today, first, days, person_id):
        if first == date(2026, 11, 1):
            return {pid: 11.0 for pid in population}  # five days into November
        return {pid: 30.0 for pid in population}

    monkeypatch.setattr(uplift, "_values", fake_values)
    graph = ai_year.person_months(conn, "p-ann", team_scope(conn, None), "story_points_done",
                                  date(2026, 7, 23), date(2026, 11, 5), "UTC")
    conn.close()
    running = graph["blocks"][-1]
    assert running["partial"] is True and running["value"] == 11.0 and running["median"] == 11.0  # no projection
    assert graph["person"]["after"]["count"] == 4  # Jul to Oct; the running month is not a whole month
    assert graph["person"]["after"]["median"] == 30.0 and graph["everyone"]["after"]["median"] == 30.0


def test_story_points_split_by_project_add_up(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from delivery_analysis.metrics import uplift
    from delivery_analysis.metrics.people import People, team_scope
    from delivery_analysis.store import db

    _client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    issues = [{"source_id": "1", "key": "MD-1", "story_points": 3.0}, {"source_id": "2", "key": "C3-7", "story_points": 5.0},
              {"source_id": "3", "key": "C3-8", "story_points": 2.0}, {"source_id": "4", "key": "MD-2", "story_points": None}]
    shares = {"1": {"person:p-ann": 1.0}, "2": {"person:p-ann": 0.5, "person:p-bob": 0.5},
              "3": {"person:p-bob": 1.0}, "4": {"person:p-ann": 1.0}}
    monkeypatch.setattr(ai_year, "credit_for", lambda conn, window: SimpleNamespace(issues=issues, shares=shares))
    assert ai_year.project_points(conn, People(conn), "p-ann", "UTC", date(2026, 11, 5), date(2026, 10, 1), 31) == {
        "C3": 2.5, "MD": 3.0}
    assert ai_year.project_points(conn, People(conn), "p-bob", "UTC", date(2026, 11, 5), date(2026, 10, 1), 31) == {
        "C3": 4.5}

    monkeypatch.setattr(uplift, "_values", lambda *a: {pid: 5.5 for pid in a[4]})
    graph = ai_year.person_months(conn, "p-ann", team_scope(conn, None), "story_points_done",
                                  date(2026, 7, 23), date(2026, 11, 5), "UTC")
    assert graph["projects"] == ["MD", "C3"]  # biggest first
    assert graph["blocks"][0]["projects"] == {"C3": 2.5, "MD": 3.0}
    other = ai_year.person_months(conn, "p-ann", team_scope(conn, None), "prs_merged",
                                  date(2026, 7, 23), date(2026, 11, 5), "UTC")
    assert "projects" not in other and "projects" not in other["blocks"][0]
    conn.close()
