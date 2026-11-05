import os
from datetime import date

import pytest

from delivery_analysis.app import api_uplift
from test_app_api import make

MEMBERS = [{"person_id": "p-ann", "name": "Ann <b>Example</b>", "level": "Mid", "day0": "2026-09-19"}]
BLOCK = {"index": 0, "start": "2026-09-19", "days": 30, "partial": False, "value": 46.0, "median": 24.0, "average": 31.0}
WINDOW = {"label": "Days 1-30", "start": "2026-09-19", "days": 30, "reached": 30, "complete": True,
          "total": 46.0, "prorated": 46.0, "median": 24.0, "average": 31.0, "before_median": 24.0, "uplift": 1.9}


@pytest.fixture
def fakes(monkeypatch):
    calls = []
    if os.environ.get("SUPERLITE_REAL") == "1":
        return calls
    monkeypatch.setattr(api_uplift.cohort, "list_members", lambda conn: MEMBERS)
    monkeypatch.setattr(api_uplift.coverage, "data_coverage", lambda conn: {"pull_requests": "2026-06-12"})

    def person_blocks(conn, pid, scope, metric, day0, today, tz, group=None):
        calls.append(("blocks", metric, scope.team_id))
        calls.append(("group", "blocks", group))
        return {"person": {"before": {"median": 1.0}, "after": {"median": 43.5}}, "blocks": [BLOCK]}

    monkeypatch.setattr(api_uplift.uplift, "person_blocks", person_blocks)

    def windows(conn, pid, scope, metric, d, t, tz, group=None):
        calls.append(("group", "windows", group))
        return [WINDOW]

    def metric_table(conn, pid, scope, names, d, t, tz, group=None):
        calls.append(("group", "table", group))
        return [{"metric": n} for n in names]

    monkeypatch.setattr(api_uplift.uplift, "windows", windows)
    monkeypatch.setattr(api_uplift.uplift, "metric_table", metric_table)

    def verdicts(level, label, facts):
        calls.append(("verdicts", level, label, facts))
        return [{"item": "Pace", "verdict": "Hit"}]

    monkeypatch.setattr(api_uplift.verdicts, "verdicts", verdicts)
    monkeypatch.setattr(api_uplift.ai_weekly, "weekly", lambda conn, pid, s, e, tz: {"starts": "2026-07-23", "weeks": []})
    monkeypatch.setattr(api_uplift.explain, "explain", lambda conn, pid, d, t, points: ["Not visible in the data."])
    return calls


def test_not_in_cohort_404(tmp_path, fakes):
    client, *_ = make(tmp_path)
    r = client.get("/api/uplift/person/p-bob")
    assert r.status_code == 404 and r.json() == {"detail": "p-bob is not in the cohort."}


def _needs_fakes():
    if os.environ.get("SUPERLITE_REAL") == "1":
        pytest.skip("uses fakes; test_real_metrics_layer_without_fakes covers the real layer")


def _blk(index, value, median, partial=False):
    return {"index": index, "start": "2026-01-01", "days": 30, "partial": partial,
            "value": value, "median": median, "average": median}


def test_at_or_above_median_counts_ended_blocks_only(tmp_path, monkeypatch):
    blocks = [_blk(-3, 5.0, 4.0), _blk(-2, 4.0, 4.0), _blk(-1, 3.0, 4.0),
              _blk(0, 9.0, 4.0), _blk(1, 1.0, 4.0, partial=True)]
    monkeypatch.setattr(api_uplift.cohort, "list_members", lambda conn: MEMBERS)
    monkeypatch.setattr(api_uplift.coverage, "data_coverage", lambda conn: {})
    monkeypatch.setattr(api_uplift.uplift, "person_blocks",
                        lambda conn, pid, scope, metric, day0, today, tz, group=None: {"blocks": blocks})
    client, *_ = make(tmp_path)
    p = client.get("/api/uplift/cohort").json()["people"][0]
    assert p["at_or_above_median"] == {"before": {"count": 2, "of": 3}, "after": {"count": 1, "of": 1}}


def test_team_param(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    assert client.get("/api/uplift/person/p-ann", params={"team": "t1"}).status_code == 200
    assert ("blocks", "story_points_done", "t1") in fakes
    assert client.get("/api/uplift/person/p-ann", params={"team": "nope"}).status_code == 404
    assert client.get("/api/uplift/cohort", params={"team": "nope"}).status_code == 404


def test_names_raw(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    body = client.get("/api/uplift/cohort").json()
    assert body["people"][0]["name"] == "Ann <b>Example</b>"


def test_cohort_payload(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    body = client.get("/api/uplift/cohort").json()
    assert body["coverage"] == {"pull_requests": "2026-06-12"}
    p = body["people"][0]
    assert p["person_id"] == "p-ann" and p["level"] == "Mid" and p["day0"] == "2026-09-19"
    assert p["day_reached"] == 26 and p["grid"] == [BLOCK] and "person" in p["points"]


def test_person_payload(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    body = client.get("/api/uplift/person/p-ann").json()
    assert {"person", "level", "day0", "day_reached", "coverage", "graphs", "points_by_merge", "windows",
            "verdicts", "quality", "how_they_worked", "ai", "explain"} <= set(body)
    assert list(body["graphs"]) == ["story_points_done", "prs_merged", "reviews_given"]
    assert all("blocks" in g and "table" in g for g in body["graphs"].values())
    assert [q["metric"] for q in body["quality"]] == [
        "prs_with_tests", "comments_received_per_pr", "durability", "inline_comments_given"]
    assert body["quality"][0]["threshold"] == 0.7 and body["quality"][1]["threshold"] == 1.2
    assert "big_tickets" in body["how_they_worked"]
    assert body["verdicts"][0]["label"] == "Days 1-30" and body["verdicts"][0]["items"][0]["item"] == "Pace"
    facts = [c for c in fakes if c[0] == "verdicts"][0][3]
    assert facts["pace_per30"] == 46.0 and facts["before_median"] == 24.0 and facts["median_per30"] == 24.0


def _groups(fakes, kind):
    return [c[2] for c in fakes if c[0] == "group" and c[1] == kind]


def _compare(client, value, path="/api/uplift/person/p-ann", **extra):
    return client.get(path, params={"compare": value, **extra})


def test_compare_everyone_is_the_default(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    for path in ("/api/uplift/person/p-ann", "/api/uplift/cohort"):
        body = client.get(path).json()
        assert body["compare"] == {"value": "everyone", "label": "Everyone", "size": 3}
    assert all(group is None for group in _groups(fakes, "blocks"))
    assert _compare(client, "everyone").json()["compare"]["size"] == 3


def test_compare_team_group_and_cohort_sizes(tmp_path, fakes):
    _needs_fakes()
    client, path, *_ = make(tmp_path)
    team = _compare(client, "team:t1").json()["compare"]
    assert team == {"value": "team:t1", "label": "Core", "size": 2}
    both = {"p-ann", "p-bob"}  # Cy is inactive, Dee excluded
    assert set(_groups(fakes, "blocks")[-1]) == both
    assert set(_groups(fakes, "windows")[-1]) == both and set(_groups(fakes, "table")[-1]) == both
    assert client.get("/api/uplift/cohort", params={"compare": "team:t1"}).json()["compare"]["size"] == 2
    assert _compare(client, "cohort").json()["compare"] == {"value": "cohort", "label": "My direct reports", "size": 1}
    assert _groups(fakes, "blocks")[-1] == ["p-ann"]


def test_compare_group_falls_back_to_the_team_with_a_note(tmp_path, fakes):
    _needs_fakes()
    from delivery_analysis.store import comparison, db

    client, path, *_ = make(tmp_path)
    info = _compare(client, "group:t1").json()["compare"]
    assert info["size"] == 2 and info["label"] == "Core comparison group"
    assert "No comparison group is saved" in info["note"]
    conn = db.connect(path)
    comparison.set_group(conn, "t1", ["p-bob"])
    conn.close()
    info = client.get("/api/uplift/cohort", params={"compare": "group:t1"}).json()["compare"]
    assert info == {"value": "group:t1", "label": "Core comparison group", "size": 1}
    assert _groups(fakes, "blocks")[-1] == ["p-bob"]


def test_compare_bad_value_and_unknown_team(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    for path in ("/api/uplift/person/p-ann", "/api/uplift/cohort"):
        bad = _compare(client, "everybody", path=path)
        assert bad.status_code == 400 and "Unknown compare value" in bad.json()["detail"]
        assert _compare(client, "team:", path=path).status_code == 400
        assert _compare(client, "team:nope", path=path).status_code == 404
        assert _compare(client, "group:nope", path=path).status_code == 404


def test_compare_keeps_team_for_repositories(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    body = _compare(client, "cohort", team="t1").json()
    assert ("blocks", "story_points_done", "t1") in fakes
    assert body["compare"]["size"] == 1


def test_compare_group_outside_the_team_uses_everyone_with_a_note(tmp_path, fakes):
    _needs_fakes()
    from delivery_analysis.store import db

    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    conn.execute("INSERT INTO team (team_id, name, window_days, created_at) VALUES ('t2', 'Other', 90, '2026-10-01')")
    conn.execute("INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit, pinned, manual) "
                 "VALUES ('t2', 'p-cy', 'active', '2026-07-01', '2026-10-01', 0, 0)")
    conn.commit()
    conn.close()
    info = _compare(client, "team:t2", team="t1").json()["compare"]
    assert info["size"] == 2 and "everyone is used" in info["note"]


def test_compare_people_resolves_the_chosen_people(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    for path in ("/api/uplift/person/p-ann", "/api/uplift/cohort"):
        info = _compare(client, "people:p-ann,p-bob,p-ann", path=path).json()["compare"]
        assert info == {"value": "people:p-ann,p-bob,p-ann", "label": "2 chosen people", "size": 2}
    assert set(_groups(fakes, "blocks")[-1]) == {"p-ann", "p-bob"} and len(_groups(fakes, "blocks")[-1]) == 2
    assert set(_groups(fakes, "windows")[-1]) == {"p-ann", "p-bob"}


def test_compare_people_bad_ids_and_empty_list_are_400(tmp_path, fakes):
    _needs_fakes()
    client, *_ = make(tmp_path)
    for path in ("/api/uplift/person/p-ann", "/api/uplift/cohort"):
        unknown = _compare(client, "people:p-ann,p-nobody", path=path)
        assert unknown.status_code == 400 and "p-nobody" in unknown.json()["detail"]
        excluded = _compare(client, "people:p-ann,p-dee", path=path)
        assert excluded.status_code == 400 and "p-dee" in excluded.json()["detail"]
        for empty in ("people:", "people:,"):
            assert _compare(client, empty, path=path).status_code == 400


def test_real_layer_compare_people_changes_the_median(tmp_path):
    from delivery_analysis.store import cohort, db

    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    cohort.set_member(conn, "p-ann", "Mid", "2026-09-19")
    conn.close()

    def medians(value):
        body = client.get("/api/uplift/person/p-ann", params={"compare": value})
        assert body.status_code == 200, body.text
        return [b["median"] for b in body.json()["graphs"]["prs_merged"]["blocks"]["blocks"]], body.json()["compare"]

    everyone, _ = medians("everyone")
    chosen, info = medians("people:p-ann,p-bob")
    assert info["size"] == 2 and info["label"] == "2 chosen people"
    assert chosen != everyone


def test_compare_options_lists_the_four_kinds(tmp_path, fakes):
    _needs_fakes()
    from delivery_analysis.store import comparison, db

    client, path, *_ = make(tmp_path)
    options = client.get("/api/uplift/compare-options").json()["options"]
    assert options == [
        {"value": "everyone", "label": "Everyone", "size": 3},
        {"value": "team:t1", "label": "Core", "size": 2},
        {"value": "group:t1", "label": "Core comparison group", "size": 2},
        {"value": "cohort", "label": "My direct reports", "size": 1},
        {"value": "people:", "label": "Custom people…", "size": None},
    ]
    conn = db.connect(path)
    comparison.set_group(conn, "t1", ["p-ann"])
    conn.close()
    again = client.get("/api/uplift/compare-options").json()["options"]
    assert {o["value"]: o["size"] for o in again}["group:t1"] == 1


def test_facts_scale_window_points_to_30_days():
    win = {"label": "Days 1-60", "days": 60, "prorated": 92.0, "total": 80.0, "median": 48.0, "before_median": 24.0}
    facts = api_uplift._facts({"story_points_done": {"Days 1-60": win}}, "Days 1-60")
    assert facts["pace_per30"] == 46.0 and facts["median_per30"] == 24.0 and facts["before_median"] == 24.0


def test_pages_served(tmp_path):
    client, *_ = make(tmp_path)
    assert client.get("/uplift").status_code == 200
    assert client.get("/uplift/person").status_code == 200


def test_real_metrics_layer_without_fakes(tmp_path):
    from delivery_analysis.store import cohort, db

    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    person_id = conn.execute("SELECT person_id FROM person ORDER BY person_id").fetchone()["person_id"]
    cohort.set_member(conn, person_id, "Mid", "2026-09-19")
    conn.close()
    body = client.get(f"/api/uplift/person/{person_id}")
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["verdicts"] and data["graphs"]["story_points_done"]["blocks"]["blocks"]
    assert client.get("/api/uplift/cohort").json()["people"][0]["person_id"] == person_id
    assert client.get("/api/uplift/person/p-nobody").status_code == 404


def test_real_layer_with_compare(tmp_path):
    from delivery_analysis.store import cohort, db

    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    cohort.set_member(conn, "p-ann", "Mid", "2026-09-19")
    conn.close()
    for value, size in (("team:t1", 2), ("group:t1", 2), ("cohort", 1), ("everyone", 3)):
        body = client.get("/api/uplift/person/p-ann", params={"compare": value})
        assert body.status_code == 200, body.text
        assert body.json()["compare"]["size"] == size
    assert client.get("/api/uplift/cohort", params={"compare": "team:t1"}).json()["compare"]["size"] == 2
