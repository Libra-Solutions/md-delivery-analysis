import pytest
from fastapi.testclient import TestClient

from metrics_seed import NOW, REPO, seed
from delivery_analysis.app.server import create_app
from delivery_analysis.app.version import data_version
from delivery_analysis.store import db, repo_selection

ORIGIN = {"origin": "http://127.0.0.1"}


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    seed(conn)
    repo_selection.add_repo(conn, "bitbucket", REPO, "ws", "core-repo", NOW)
    conn.close()
    return TestClient(create_app(path), base_url="http://127.0.0.1")


def test_version_changes_after_a_write_but_not_after_a_read(client):
    v1 = client.get("/api/version").json()["version"]
    assert len(v1) == 12
    assert client.get("/api/teams").status_code == 200
    assert client.get("/api/version").json()["version"] == v1
    assert client.get("/api/version").json()["version"] == v1
    r = client.post("/api/teams", json={"name": "Fresh", "repos": ["bitbucket:core-repo"]}, headers=ORIGIN)
    assert r.status_code < 400, r.text
    assert client.get("/api/version").json()["version"] != v1


def test_failed_write_does_not_change_the_version(client):
    v1 = client.get("/api/version").json()["version"]
    assert client.post("/api/teams", json={"name": "", "repos": []}, headers=ORIGIN).status_code == 400
    assert client.get("/api/version").json()["version"] == v1


def test_refresh_post_does_not_bump_the_write_counter(client):
    client.post("/api/refresh", json={"only_stale": True}, headers=ORIGIN)
    assert client.app.state.context.write_count == 0


def test_data_version_is_stable_on_repeat_calls(client):
    ctx = client.app.state.context
    assert data_version(ctx) == data_version(ctx)
