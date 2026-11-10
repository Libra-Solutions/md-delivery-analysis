from fastapi.testclient import TestClient

from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.server import create_app
from delivery_analysis.settings import Settings

HOST = "delivery.example"


def _client(tmp_path, base_url, public_hosts=(HOST,)):
    path = tmp_path / "d.sqlite"
    app = create_app(path, settings=Settings(db_path=path), environ={}, worker=RefreshWorker(lambda s, f: "ok"),
                     port=8000, public_hosts=public_hosts)
    return TestClient(app, base_url=base_url)


def test_public_host_is_refused_unless_configured(tmp_path):
    assert _client(tmp_path, f"https://{HOST}", public_hosts=()).get("/api/health").status_code == 403
    assert _client(tmp_path, f"https://{HOST}").get("/api/health").status_code == 200
    assert _client(tmp_path, "https://other.example").get("/api/health").status_code == 403


def test_public_host_writes_need_an_https_origin_on_that_host(tmp_path):
    client = _client(tmp_path, f"https://{HOST}")
    for origin, code in ((f"https://{HOST}", 200), (f"http://{HOST}", 403), (f"https://{HOST}:8443", 403),
                         ("https://evil.example", 403), ("http://127.0.0.1:8000", 200)):
        status = client.post("/api/refresh", json={}, headers={"Origin": origin}).status_code
        assert (status == 403) == (code == 403), origin


def test_settings_read_bind_host_and_public_hosts():
    s = Settings.from_env({"BIND_HOST": "0.0.0.0", "PUBLIC_HOSTS": " A.example , b.example ,"})
    assert s.host == "0.0.0.0" and s.public_hosts == ("a.example", "b.example")
    assert Settings.from_env({}).host == "127.0.0.1" and Settings.from_env({}).public_hosts == ()


def test_sqlite_journal_mode_can_be_set_for_network_storage(tmp_path, monkeypatch):
    from delivery_analysis.store import db
    monkeypatch.setenv("SQLITE_JOURNAL_MODE", "delete")
    assert db.connect(tmp_path / "a.sqlite").execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    monkeypatch.setenv("SQLITE_JOURNAL_MODE", "bogus; DROP")
    assert db.connect(tmp_path / "b.sqlite").execute("PRAGMA journal_mode").fetchone()[0] == "wal"
