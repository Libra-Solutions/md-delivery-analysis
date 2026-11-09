from fastapi.testclient import TestClient

from delivery_analysis.app.server import PAGES, create_app
from delivery_analysis.store import db
from delivery_analysis.store import sync_state as ss

NAV_LABELS = ["Dashboard", "Rankings", "People", "Selection", "Teams", "Sources", "Settings", "Ask"]


def test_server_starts_on_an_empty_database_in_a_new_folder(tmp_path):
    target = tmp_path / "fresh" / "folder" / "delivery.sqlite"
    client = TestClient(create_app(target), base_url="http://127.0.0.1")
    body = client.get("/api/health").json()
    assert body == {"schema_version": 8, "sources": [], "unmapped_identities": 0}
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


def test_every_page_serves_the_shell_with_all_seven_nav_links(tmp_path):
    client = TestClient(create_app(tmp_path / "d.sqlite"), base_url="http://127.0.0.1")
    assert len(PAGES) == 10
    for page in PAGES:
        response = client.get(page)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        for label in NAV_LABELS:
            assert label in response.text


def test_unknown_page_is_404(tmp_path):
    client = TestClient(create_app(tmp_path / "d.sqlite"), base_url="http://127.0.0.1")
    assert client.get("/nope").status_code == 404


def test_pages_and_static_files_are_revalidated_so_updates_show_without_a_hard_refresh(tmp_path):
    client = TestClient(create_app(tmp_path / "d.sqlite"), base_url="http://127.0.0.1")
    for url in ("/person", "/static/pages/person.js", "/static/style.css"):
        assert client.get(url).headers.get("cache-control") == "no-cache", url
