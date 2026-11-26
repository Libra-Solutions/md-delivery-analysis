from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from metrics_seed import NOW, REPO, seed
from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.server import create_app
from delivery_analysis.settings import Settings
from delivery_analysis.store import db, repo_selection, sync_state

CLOCK = lambda: datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc)  # noqa: E731
TOKEN = "tok-bb-API-LEAK-1"


class FakeRun:
    def __init__(self, result="1 ok, 0 failed", error=None):
        self.calls = []
        self.result = result
        self.error = error

    def __call__(self, source, full):
        self.calls.append((source, full))
        if self.error:
            raise RuntimeError(self.error)
        return self.result


def make(tmp_path, *, environ=None, run=None, transport=None, seeded=True):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    if seeded:
        seed(conn)
        repo_selection.add_repo(conn, "bitbucket", REPO, "ws", "core-repo", NOW)
    conn.close()
    fake = run or FakeRun()
    worker = RefreshWorker(fake)
    app = create_app(
        path, settings=Settings(db_path=path), environ=environ or {}, worker=worker,
        clock=CLOCK, transport=transport, port=8000,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    return client, path, worker, fake


def test_teams_list_and_detail(tmp_path):
    client, *_ = make(tmp_path)
    teams = client.get("/api/teams").json()["teams"]
    assert teams == [{
        "team_id": "t1", "name": "Core", "window_days": 90,
        "repos": [{"source": "bitbucket", "repository_id": REPO, "name": "core-repo"}],
        "members": {"active": 2, "inactive": 1, "excluded": 1},
    }]
    detail = client.get("/api/teams/t1").json()
    ann = [m for m in detail["members"] if m["person_id"] == "p-ann"][0]
    assert ann["accounts"] == ["acc-ann"] and ann["emails"] == ["ann@corp.example"] and ann["status"] == "active"
    assert detail["possible_duplicates"] == []
    assert client.get("/api/teams/nope").status_code == 404


def test_metrics_listing_and_one_metric(tmp_path):
    client, *_ = make(tmp_path)
    listing = {m["name"]: m for m in client.get("/api/metrics").json()["metrics"]}
    assert listing["prs_merged"]["status"] == "ok" and listing["cycle_time"]["status"] == "waiting"
    body = client.get("/api/metrics/prs_merged", params={"team": "t1", "window": "month:2026-09"}).json()
    assert body["window"]["label"] == "September 2026"
    assert [(r["name"], r["value"]) for r in body["rows"]] == [("Ann Example", 3.0), ("Bob Builder", 0.0)]
    inactive = client.get("/api/metrics/prs_merged",
                          params={"team": "t1", "window": "month:2026-09", "include_inactive": "true"}).json()
    assert "Cy Inactive" in [r["name"] for r in inactive["rows"]]
    custom = client.get("/api/metrics/prs_merged",
                        params={"window": "custom", "from": "2026-09-01", "to": "2026-09-30"}).json()
    assert custom["window"]["days"] == 30


@pytest.mark.parametrize(
    "path, params, status",
    [("/api/metrics/nope", {}, 404), ("/api/metrics/prs_merged", {"window": "weekly"}, 400),
     ("/api/metrics/prs_merged", {"team": "nope"}, 404)],
)
def test_metric_errors_are_plain(tmp_path, path, params, status):
    client, *_ = make(tmp_path)
    response = client.get(path, params=params)
    assert response.status_code == status and response.json()["detail"]


def test_default_window_uses_the_team_window_and_today_from_the_clock(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/metrics/prs_merged", params={"team": "t1"}).json()
    assert body["window"] == {"start": "2026-07-18T04:00:00Z", "end": "2026-10-16T04:00:00Z",
                              "label": "Last 90 days", "days": 90}


def test_person_detail_and_unknown_person(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/people/p-ann", params={"team": "t1", "window": "month:2026-09"}).json()
    assert body["person"]["name"] == "Ann Example" and len(body["pull_requests"]) == 3
    assert client.get("/api/people/nobody").status_code == 404


def test_unmapped_identities_and_people(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/identities/unmapped").json()
    assert body["unmapped"] == [{"source": "bitbucket", "account": "acc-zed", "activity": 2, "name_hint": None}]
    assert [p["name"] for p in body["people"]] == ["Ann Example", "Bob Builder", "Cy Inactive"]


def test_repos_and_sources_with_detail_progress_and_labels(tmp_path):
    client, path, *_ = make(tmp_path, environ={"BITBUCKET": TOKEN})
    conn = db.connect(path)
    sync_state.save_state(conn, "bitbucket", REPO, status="failed", error=f"boom {TOKEN}", records=0,
                          now="2026-10-15T15:30:00Z")
    conn.close()
    repos = client.get("/api/repos").json()["repos"]
    assert repos[0]["slug"] == "core-repo" and (repos[0]["detail_done"], repos[0]["detail_total"]) == (4, 5)
    sources = client.get("/api/sources").json()
    row = sources["sources"][0]
    assert (row["label"], row["failed"], row["age_minutes"]) == ("ws/core-repo", True, 30)
    assert TOKEN not in str(sources)
    assert sources["configured"] == ["bitbucket"] and "jira" in sources["waiting"]
    assert sources["refresh"]["running"] is False and sources["refresh_after_minutes"] == 60


def test_settings_show_names_never_values(tmp_path):
    client, *_ = make(tmp_path, environ={"BITBUCKET": TOKEN})
    body = client.get("/api/settings").json()
    assert body["credentials"]["BITBUCKET"] is True and body["credentials"]["ATLASSIAN"] is False
    assert body["report_tz"] == "America/New_York" and body["window_days"] == 90
    assert TOKEN not in str(body)


def test_settings_list_the_atlassian_email_by_name(tmp_path):
    client, *_ = make(tmp_path, environ={"ATLASSIAN_EMAIL": "me@corp.example"})
    body = client.get("/api/settings").json()
    assert body["credentials"]["ATLASSIAN_EMAIL"] is True
    assert "me@corp.example" not in str(body)
    other, *_ = make(tmp_path / "b", environ={})
    assert other.get("/api/settings").json()["credentials"]["ATLASSIAN_EMAIL"] is False


@pytest.mark.parametrize("host", ["evil.example", "192.168.1.5:8000", "127.0.0.1.evil.example"])
def test_requests_for_other_hosts_are_refused(tmp_path, host):
    client, *_ = make(tmp_path)
    response = client.get("/api/teams", headers={"Host": host})
    assert response.status_code == 403


def test_localhost_names_are_accepted(tmp_path):
    client, *_ = make(tmp_path)
    for host in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
        assert client.get("/api/teams", headers={"Host": host}).status_code == 200


def test_people_matrix_endpoint(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/people-matrix", params={"team": "t1", "window": "month:2026-09"}).json()
    assert set(body) == {"window", "columns", "rows", "notes"}
    assert body["columns"][0]["name"] == "impact_points"
    bob = [r for r in body["rows"] if r["person_id"] == "p-bob"][0]
    assert bob["cells"]["prs_reviewed"]["value"] == 1.0
    assert "p-cy" not in [r["person_id"] for r in body["rows"]]
    assert client.get("/api/people-matrix", params={"team": "nope"}).status_code == 404
    assert client.get("/api/people-matrix", params={"window": "weekly"}).status_code == 400


def test_person_series_returns_the_rolling_series(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/person/p-ann/series",
                      params={"team": "t1", "window_days": 30, "step_days": 30, "history_days": 60}).json()
    assert body["dates"] == ["2026-08-16", "2026-09-15", "2026-10-15"]
    assert set(body["series"]) == set(body["team_median"]) == {
        "impact", "delivery", "participation", "penalty", "impact_per_dollar", "prs_reviewed", "review_value",
        "delivery_speed", "durability",
    }
    assert all(len(values) == 3 for values in body["series"].values())
    assert body["series"]["prs_reviewed"][0] == 0
    summary = body["summary"]
    assert (summary["window_days"], summary["end"], summary["start"]) == (30, "2026-10-15", "2026-09-16")
    assert summary["impact"] == body["series"]["impact"][-1]
    assert set(summary) == {"window_days", "start", "end", "impact", "claude_cost", "impact_per_dollar",
                            "team_median_impact_per_dollar"}


def test_person_series_defaults_and_no_team(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/person/p-ann/series").json()
    assert len(body["dates"]) == 26 and body["dates"][-1] == "2026-10-15" and body["window_days"] == 30


@pytest.mark.parametrize("path, params, status", [
    ("/api/person/nope/series", {}, 404),
    ("/api/person/p-ann/series", {"team": "nope"}, 404),
    ("/api/person/p-ann/series", {"window_days": 6}, 400),
    ("/api/person/p-ann/series", {"window_days": 366}, 400),
    ("/api/person/p-ann/series", {"step_days": 0}, 400),
    ("/api/person/p-ann/series", {"window_days": 30, "step_days": 31}, 400),
    ("/api/person/p-ann/series", {"history_days": 731}, 400),
    ("/api/person/p-ann/series", {"history_days": -1}, 400),
    ("/api/person/p-ann/series", {"history_days": 730}, 200),
])
def test_person_series_validates_its_parameters(tmp_path, path, params, status):
    client, *_ = make(tmp_path)
    assert client.get(path, params=params).status_code == status
