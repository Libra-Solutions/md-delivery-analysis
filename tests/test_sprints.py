import json
from datetime import date

from delivery_analysis.metrics import sprints
from delivery_analysis.store import db
from test_app_api import make


def _sprint(sid, board, name, start, end, state="closed", complete=None):
    item = {"id": sid, "boardId": board, "name": name, "state": state,
            "startDate": start + "T09:00:00.000Z", "endDate": end + "T17:00:00.000Z"}
    if complete:
        item["completeDate"] = complete + "T12:00:00.000Z"
    return item


def _issue(conn, issue_id, sprint_list, field="customfield_10006"):
    payload = {"id": issue_id, "key": f"AB-{issue_id}", "fields": {"summary": "x", field: sprint_list}}
    conn.execute("INSERT INTO raw_payload (source, source_id, kind, json, fetched_at) VALUES ('jira', ?, 'issue', ?, '2026-10-01')",
                 (issue_id, json.dumps(payload)))


def _credit(conn, issue_id, person_id):
    conn.execute("INSERT INTO ticket_credit (work_item_source, work_item_id, person_id, share, evidence, method) "
                 "VALUES ('jira', ?, ?, 1.0, 'dev1', 'dev_field')", (issue_id, person_id))


def test_derive_reads_the_sprint_field_by_its_shape(conn):
    _issue(conn, "1", [_sprint(10, 7, "AB Sprint 1", "2026-09-01", "2026-09-15", complete="2026-09-14"),
                       _sprint(11, 7, "AB Sprint 2", "2026-09-15", "2026-09-29")])
    _issue(conn, "2", [_sprint(11, 7, "AB Sprint 2", "2026-09-15", "2026-09-29")], field="customfield_99999")
    _issue(conn, "3", [{"id": 12, "boardId": 7, "name": "AB Sprint 3", "state": "future"}])  # no dates yet
    assert sprints.derive_sprints(conn) == 2
    rows = conn.execute("SELECT sprint_id, board_id, start_at, end_at FROM sprint ORDER BY sprint_id").fetchall()
    assert [tuple(r) for r in rows] == [
        ("10", "7", "2026-09-01T09:00:00.000Z", "2026-09-14T12:00:00.000Z"),  # closed: ends on its complete date
        ("11", "7", "2026-09-15T09:00:00.000Z", "2026-09-29T17:00:00.000Z"),
    ]
    members = conn.execute("SELECT work_item_id, sprint_id FROM work_item_sprint ORDER BY 1, 2").fetchall()
    assert [tuple(m) for m in members] == [("1", "10"), ("1", "11"), ("2", "11")]
    assert sprints.derive_sprints(conn) == 2  # a rerun replaces, it does not duplicate
    assert conn.execute("SELECT COUNT(*) FROM work_item_sprint").fetchone()[0] == 3


def test_person_board_is_where_most_of_their_tickets_are(conn):
    _issue(conn, "1", [_sprint(10, 7, "AB Sprint 1", "2026-09-01", "2026-09-15")])
    _issue(conn, "2", [_sprint(20, 8, "CD Sprint 1", "2026-09-02", "2026-09-16")])
    _issue(conn, "3", [_sprint(20, 8, "CD Sprint 1", "2026-09-02", "2026-09-16")])
    sprints.derive_sprints(conn)
    for pid in ("p-a", "p-b"):
        conn.execute("INSERT INTO person (person_id, display_name, excluded, manual) VALUES (?, ?, 0, 0)", (pid, pid))
    for issue in ("1", "2", "3"):
        _credit(conn, issue, "p-a")
    _credit(conn, "1", "p-b")
    assert sprints.person_board(conn, "p-a", date(2025, 11, 1)) == "8"
    assert sprints.person_board(conn, "p-b", date(2025, 11, 1)) == "7"
    assert sprints.person_board(conn, "p-nobody", date(2025, 11, 1)) is None
    assert sprints.person_board(conn, "p-a", date(2026, 10, 1)) is None  # nothing sprinted in the window
    assert sprints.board_name(conn, "8") == "CD" and sprints.board_name(conn, "99") == "board 99"


def test_sprint_blocks_count_from_the_sprint_holding_the_ai_start(conn):
    _issue(conn, "1", [
        _sprint(1, 7, "AB Sprint 1", "2026-08-31", "2026-09-14"),
        _sprint(2, 7, "AB Sprint 2", "2026-09-14", "2026-09-28"),
        _sprint(3, 7, "AB Sprint 3", "2026-09-28", "2026-10-12"),
        _sprint(4, 7, "AB Sprint 4", "2026-10-12", "2026-10-26", state="active"),
        _sprint(5, 8, "CD Sprint 9", "2026-09-01", "2026-09-15"),  # another board
    ])
    sprints.derive_sprints(conn)
    blocks = sprints.sprint_blocks(conn, "7", date(2026, 10, 15), date(2026, 9, 20))
    assert [(b["name"], b["index"]) for b in blocks] == [
        ("AB Sprint 1", -1), ("AB Sprint 2", 0), ("AB Sprint 3", 1), ("AB Sprint 4", 2)]
    assert blocks[0] == {"index": -1, "first": "2026-08-31", "last": "2026-09-14", "name": "AB Sprint 1",
                         "at": "2026-08-31T09:00:00Z", "until": "2026-09-14T17:00:00Z",  # sprint 2 starts after it
                         "days": 15, "month_days": 15, "partial": False}
    assert blocks[-1]["partial"] is True and blocks[-1]["days"] == 4 and blocks[-1]["last"] == "2026-10-15"
    plain = sprints.sprint_blocks(conn, "7", date(2026, 10, 15), None)
    assert [b["index"] for b in plain] == [-4, -3, -2, -1]
    # An AI start after the last sprint: all are before.
    assert [b["index"] for b in sprints.sprint_blocks(conn, "7", date(2026, 10, 15), date(2026, 12, 1))] == [-4, -3, -2, -1]
    # Only sprints within the last year that have started.
    assert [b["name"] for b in sprints.sprint_blocks(conn, "7", date(2026, 10, 1), None, back_days=15)] == [
        "AB Sprint 2", "AB Sprint 3"]


def test_overlapping_sprints_on_one_board_do_not_double_count(conn):
    _issue(conn, "1", [_sprint(1, 7, "AB Sprint 1", "2026-09-01", "2026-09-15"),
                       _sprint(2, 7, "AB Sprint 2", "2026-09-10", "2026-09-24")])
    sprints.derive_sprints(conn)
    blocks = sprints.sprint_blocks(conn, "7", date(2026, 10, 1), None)
    assert [(b["at"], b["until"]) for b in blocks] == [
        ("2026-09-01T09:00:00Z", "2026-09-15T17:00:00Z"), ("2026-09-15T17:00:00Z", "2026-09-24T17:00:00Z")]


def test_year_api_by_sprint(tmp_path):
    from delivery_analysis.store import cohort

    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    cohort.set_member(conn, "p-ann", "Senior", "2026-09-19")
    conn.execute(
        "INSERT INTO token_usage (person_id, day, model, purpose, cost_usd, source, purpose_method, purpose_confidence) "
        "VALUES ('p-ann', '2026-09-20', 'm', 'unclassified', 1.0, 'claude_code', 'none', 'low')")
    _issue(conn, "9001", [_sprint(1, 7, "AB Sprint 1", "2026-08-31", "2026-09-14"),
                          _sprint(2, 7, "AB Sprint 2", "2026-09-14", "2026-09-28"),
                          _sprint(3, 7, "AB Sprint 3", "2026-09-28", "2026-10-12"),
                          _sprint(4, 7, "AB Sprint 4", "2026-10-12", "2026-10-26", state="active")])
    sprints.derive_sprints(conn)
    _credit(conn, "9001", "p-ann")
    conn.close()

    data = client.get("/api/uplift/year/person/p-ann", params={"by": "sprint"}).json()
    assert data["by"] == "sprint" and data["board"] == {"board_id": "7", "name": "AB"}
    graph = data["graphs"]["prs_merged"]
    assert [b["name"] for b in graph["blocks"]] == ["AB Sprint 1", "AB Sprint 2", "AB Sprint 3", "AB Sprint 4"]
    assert [b["index"] for b in graph["blocks"]] == [-1, 0, 1, 2]
    assert graph["blocks"][0]["start"] == "2026-08-31" and graph["blocks"][-1]["partial"] is True
    assert data["expectations"][0]["first"] == "2026-08-31"  # the year starts at the first sprint
    assert "AB board" in data["notes"][0] and any("sprint of the AI start" in n for n in data["notes"])

    months = client.get("/api/uplift/year/person/p-ann").json()
    assert months["by"] == "month" and len(months["graphs"]["prs_merged"]["blocks"]) == 12

    nobody = client.get("/api/uplift/year/person/p-bob", params={"by": "sprint"})
    assert nobody.status_code == 404 or nobody.json()["board"] is None
    assert client.get("/api/uplift/year/person/p-ann", params={"by": "week"}).status_code == 400


def test_closed_snapshot_of_a_sprint_wins_over_an_older_open_one(conn):
    _issue(conn, "1", [_sprint(86, 7, "AB Sprint 86", "2026-10-21", "2026-11-04", state="active")])
    _issue(conn, "2", [_sprint(86, 7, "AB Sprint 86", "2026-10-21", "2026-11-04", complete="2026-11-05")])
    _issue(conn, "3", [_sprint(86, 7, "AB Sprint 86", "2026-10-21", "2026-11-04", state="active")])
    sprints.derive_sprints(conn)
    row = conn.execute("SELECT state, end_at FROM sprint WHERE sprint_id = '86'").fetchone()
    assert tuple(row) == ("closed", "2026-11-05T12:00:00.000Z")


def test_days_between_sprints_go_to_the_earlier_sprint(conn):
    _issue(conn, "1", [_sprint(1, 7, "AB Sprint 1", "2026-10-21", "2026-11-04"),
                       _sprint(2, 7, "AB Sprint 2", "2026-11-05", "2026-11-18", state="active")])
    sprints.derive_sprints(conn)
    blocks = sprints.sprint_blocks(conn, "7", date(2026, 11, 6), None)
    assert [(b["at"], b["until"]) for b in blocks] == [
        ("2026-10-21T09:00:00Z", "2026-11-05T09:00:00Z"), ("2026-11-05T09:00:00Z", "2026-11-18T17:00:00Z")]
    assert blocks[0]["partial"] is False and blocks[1]["partial"] is True


def test_sprint_numbers_use_exact_times(tmp_path, monkeypatch):
    from delivery_analysis.metrics import ai_year, uplift
    from delivery_analysis.metrics.people import team_scope

    _client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    _issue(conn, "1", [_sprint(1, 7, "AB Sprint 1", "2026-10-21", "2026-11-04", complete="2026-11-05")])
    sprints.derive_sprints(conn)
    seen = []

    def fake_values(conn, metric, scope, people, population, tz, today, first, days, person_id, bounds=None):
        seen.append(bounds)
        return {pid: 1.0 for pid in population}

    monkeypatch.setattr(uplift, "_values", fake_values)
    layout = sprints.sprint_blocks(conn, "7", date(2026, 11, 6), None)
    ai_year.person_months(conn, "p-ann", team_scope(conn, None), "prs_merged", None, date(2026, 11, 6), "UTC",
                          layout=layout)
    conn.close()
    assert seen == [("2026-10-21T09:00:00Z", "2026-11-05T12:00:00Z")]
