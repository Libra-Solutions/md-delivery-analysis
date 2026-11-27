import threading

import pytest
from fastapi.testclient import TestClient

from metrics_seed import NOW, REPO, seed
from delivery_analysis.app.server import create_app
from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.version import data_version
from delivery_analysis.settings import Settings
from delivery_analysis.store import db, repo_selection
from delivery_analysis.store.sync_state import save_state

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



def _sync_app(tmp_path):
    """An app whose refresh writes a sync state, then waits until released."""
    path = tmp_path / "s.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    conn.close()
    wrote, release = threading.Event(), threading.Event()

    def run(source, full):
        c = db.connect(path)
        save_state(c, "bitbucket", "repo-a", status="ok", error=None, records=1, now="2026-11-27T10:00:00Z")
        c.commit()
        c.close()
        wrote.set()
        release.wait(5)
        return "done"

    worker = RefreshWorker(run)
    app = create_app(path, settings=Settings(db_path=path), environ={}, worker=worker)
    return TestClient(app, base_url="http://127.0.0.1"), worker, wrote, release


def test_version_holds_while_a_refresh_runs_and_changes_once_it_ends(tmp_path):
    client, worker, wrote, release = _sync_app(tmp_path)
    v1 = client.get("/api/version").json()["version"]
    assert worker.start()
    try:
        assert wrote.wait(5)
        assert client.get("/api/version").json()["version"] == v1
    finally:
        release.set()
        worker.wait()
    assert client.get("/api/version").json()["version"] != v1


def test_a_write_during_a_refresh_still_changes_the_version(tmp_path):
    client, worker, wrote, release = _sync_app(tmp_path)
    v1 = client.get("/api/version").json()["version"]
    assert worker.start()
    try:
        assert wrote.wait(5)
        client.app.state.context.write_count += 1  # what the middleware does after a successful write
        assert client.get("/api/version").json()["version"] != v1
    finally:
        release.set()
        worker.wait()
