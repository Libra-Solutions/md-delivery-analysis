from datetime import datetime, timezone

from fastapi.testclient import TestClient

from qa_seed import seed_dashboard
from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.server import create_app
from delivery_analysis.settings import Settings
from delivery_analysis.store import db

CLOCK = lambda: datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc)  # noqa: E731


def make(tmp_path):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    seed_dashboard(conn)
    conn.close()
    app = create_app(path, settings=Settings(db_path=path), environ={}, worker=RefreshWorker(lambda s, f: "ok"),
                     clock=CLOCK, port=8000)
    return TestClient(app, base_url="http://127.0.0.1")


def test_qa_api_returns_sprints_months_releases_and_no_people(tmp_path):
    client = make(tmp_path)
    response = client.get("/api/qa")
    assert response.status_code == 200
    data = response.json()
    assert [s["name"] for s in data["sprints"]] == ["MD Sprint 1", "MD Sprint 2", "MD Sprint 3"]
    assert data["headline"]["sprint"]["failed_keys"] == ["MD-5"]
    assert [r["release"] for r in data["releases"]] == ["3.36", "3.37"]
    assert "acc-tess" not in response.text


def test_qa_csv_has_one_section_per_grain(tmp_path):
    client = make(tmp_path)
    response = client.get("/api/qa/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="qa-md.csv"' in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")
    for heading in ("Sprints", "Months", "Regression bugs by release"):
        assert heading + "\r\n" in text
    assert "MD Sprint 1," in text and "3.36," in text
    assert "acc-tess" not in text
