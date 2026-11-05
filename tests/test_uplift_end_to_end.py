"""The real app over a seeded database: the uplift API agrees with the plain metrics API."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from impact_seed import issue, link_pr, seed_impact
from metrics_seed import REPO, TZ, commit, pr, put
from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.server import create_app
from delivery_analysis.settings import Settings
from delivery_analysis.store import cohort, db

# 2026-10-25 12:00 in New York: Day 36 for a Day 0 of 2026-09-19, so Days 1-30 is a complete window.
CLOCK = lambda: datetime(2026, 10, 25, 16, 0, tzinfo=timezone.utc)  # noqa: E731
DAY0 = "2026-09-19"
PERSON = "p-ann"


def _seed_after_day0(conn):
    seed_impact(conn)
    pr(conn, 8, "acc-ann", "MERGED", "2026-10-04T14:00:00Z", "2026-10-05T14:00:00Z")
    commit(conn, "e1", "acc-ann", "ann@corp.example", "2026-10-04T15:00:00Z")
    conn.execute("UPDATE vcs_commit SET change_request_id = ? WHERE sha = 'e1'", (f"{REPO}#8",))
    for path in ("src/Foo.cs", "tests/FooTests.cs", "movedocs-spa/a.ts"):
        conn.execute(
            "INSERT INTO commit_file (repository_id, sha, path, fetched_at) VALUES (?, 'e1', ?, 'x')", (REPO, path)
        )
    issue(conn, "10", "acc-ann", resolved="2026-10-05T14:00:00Z", started="2026-10-01T14:00:00Z", points=4)
    link_pr(conn, 8, "10")
    for number, actor, path in ((1, "acc-bob", "src/Foo.cs"), (2, "acc-bob", None)):
        sid = f"{REPO}#8"
        put(
            conn, "review_comment", source="bitbucket", source_id=f"{sid}:comment:{number}", change_request_id=sid,
            actor_account=actor, created_at="2026-10-04T18:00:00Z", path=path, line=3 if path else None,
            parent_id=None, resolved=0,
        )


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "e2e.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    _seed_after_day0(conn)
    cohort.set_member(conn, PERSON, "Mid", DAY0)
    conn.close()
    app = create_app(
        path, settings=Settings(db_path=path), environ={}, worker=RefreshWorker(lambda source, full: "ok"),
        clock=CLOCK, port=8000,
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_end_to_end(client):
    assert TZ.key == Settings(db_path="x").report_tz.key
    body = client.get(f"/api/uplift/person/{PERSON}")
    assert body.status_code == 200
    person = body.json()
    assert person["day0"] == DAY0 and person["day_reached"] == 36 and person["level"] == "Mid"

    first = [w for w in person["windows"] if w["label"] == "Days 1-30"][0]
    assert first["complete"] is True

    metric = client.get(
        "/api/metrics/story_points_done", params={"window": "custom", "from": DAY0, "to": "2026-10-18"}
    )
    assert metric.status_code == 200
    rows = {row["person_id"]: row for row in metric.json()["rows"]}
    expected = rows[PERSON]["value"]
    assert expected is not None and expected > 0
    assert first["total"] == pytest.approx(expected)

    assert person["verdicts"], "verdict rows are missing"
    for row in person["verdicts"]:
        assert row["label"] and isinstance(row["items"], list)
    assert any(row["items"] for row in person["verdicts"])
    assert person["graphs"]["story_points_done"]["blocks"]["blocks"]


def test_cohort_lists_member(client):
    body = client.get("/api/uplift/cohort")
    assert body.status_code == 200
    people = body.json()["people"]
    assert [(p["person_id"], p["level"], p["day0"], p["day_reached"]) for p in people] == [
        (PERSON, "Mid", DAY0, 36)
    ]
    assert client.get("/api/uplift/person/p-bob").status_code == 404
