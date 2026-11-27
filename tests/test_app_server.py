from fastapi.testclient import TestClient

from delivery_analysis.app.server import create_app
from delivery_analysis.store import db
from delivery_analysis.store import sync_state as ss
from tests.schema import LATEST_SCHEMA

def test_server_starts_on_an_empty_database_in_a_new_folder(tmp_path):
    target = tmp_path / "fresh" / "folder" / "delivery.sqlite"
    client = TestClient(create_app(target), base_url="http://127.0.0.1")
    body = client.get("/api/health").json()
    assert body == {"schema_version": LATEST_SCHEMA, "sources": [], "unmapped_identities": 0}
    assert target.is_file()


def test_health_reports_stale_sources_with_their_error(tmp_path):
    path = tmp_path / "d.sqlite"
    client = TestClient(create_app(path), base_url="http://127.0.0.1")
    conn = db.connect(path)
    ss.save_state(conn, "fake", "main", status="failed", error="source down", records=2, now="2026-05-02T00:00:00Z")
    conn.close()
    source = client.get("/api/health").json()["sources"][0]
    assert source["connector"] == "fake"
    assert source["stale"] is True
    assert source["error"] == "source down"


def test_pages_are_no_longer_served(tmp_path):
    client = TestClient(create_app(tmp_path / "d.sqlite"), base_url="http://127.0.0.1")
    assert client.get("/").status_code == 404
    assert client.get("/static/style.css").status_code == 404


def test_cross_site_write_still_403(tmp_path):
    client = TestClient(create_app(tmp_path / "d.sqlite"), base_url="http://127.0.0.1")
    r = client.post("/api/refresh", json={"only_stale": True}, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/api/refresh", json={"only_stale": True}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403


def test_writes_relayed_from_the_front_port_pass_the_origin_check(tmp_path):
    app = create_app(tmp_path / "d.sqlite", port=8001, origin_port=8000)
    c = TestClient(app, base_url="http://127.0.0.1:8001")
    body = {"only_stale": True}
    assert c.post("/api/refresh", json=body, headers={"origin": "http://127.0.0.1:8000"}).status_code < 400
    assert c.post("/api/refresh", json=body, headers={"origin": "http://127.0.0.1:8001"}).status_code == 403


def test_request_threads_caps_the_worker_threads(tmp_path):
    import anyio.to_thread
    from fastapi.testclient import TestClient
    app = create_app(tmp_path / "t.sqlite", request_threads=2)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.portal.call(lambda: anyio.to_thread.current_default_thread_limiter().total_tokens) == 2
