import json
from datetime import date
from zoneinfo import ZoneInfo

from qa_seed import C3S, S0, S1, S2, S3, link, move, qa_pass, ticket
from delivery_analysis.metrics import qa

START = date(2026, 6, 1)
TODAY = date(2026, 7, 20)


def test_last_sprint_takes_the_latest_md_sprint_and_ignores_other_boards():
    assert qa.last_sprint(json.dumps([S1, C3S, S2])) == S2
    assert qa.last_sprint(json.dumps([C3S])) is None
    assert qa.last_sprint("not json") is None
    assert qa.last_sprint(None) is None
    assert qa.last_sprint(json.dumps([{"id": 99, "name": "MD Sprint 9"}])) is None  # future: no start date


def test_list_sprints_keeps_md_sprints_starting_in_the_window(conn):
    ticket(conn, 1, "Story", "2026-05-25T00:00:00Z", [S0, S1])
    ticket(conn, 2, "Story", "2026-06-20T00:00:00Z", [S2, C3S])
    ticket(conn, 3, "Story", "2026-07-02T00:00:00Z", [S3])
    sprints = qa.list_sprints(conn, "MD", START, TODAY)
    assert [s["name"] for s in sprints] == ["MD Sprint 1", "MD Sprint 2", "MD Sprint 3"]
    assert [s["in_progress"] for s in sprints] == [False, False, True]
    assert sprints[0] == {"sprint_id": 11, "name": "MD Sprint 1", "start": S1["startDate"], "end": S1["endDate"],
                          "in_progress": False}


def test_qa_fail_rate_counts_bounces_from_qa_back_to_development(conn):
    passed = ticket(conn, 1, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, passed, "2026-06-05")
    failed = ticket(conn, 2, "Story", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, failed, "2026-06-06", bounce_from="In QA")
    carried = ticket(conn, 3, "Story", "2026-06-03T00:00:00Z", [S1, S2])  # counts in its last sprint
    qa_pass(conn, carried, "2026-06-20", bounce_from="Ready for QA")
    untested = ticket(conn, 4, "Story", "2026-06-03T00:00:00Z", [S1])
    move(conn, untested, "To Do", "In Progress", "2026-06-05T00:00:00Z")
    loose = ticket(conn, 5, "Story", "2026-06-03T00:00:00Z")
    qa_pass(conn, loose, "2026-06-10")
    bug = ticket(conn, 6, "Bug", "2026-06-03T00:00:00Z", [S1])
    qa_pass(conn, bug, "2026-06-07", bounce_from="In QA")
    sub = ticket(conn, 7, "Sub-bug", "2026-06-06T00:00:00Z", [S1])
    link(conn, sub, failed, "parent")
    ticket(conn, 8, "Story", "2026-07-02T00:00:00Z", [S3])

    sprints = qa.list_sprints(conn, "MD", START, TODAY)
    result = qa.qa_fail_by_sprint(conn, sprints, "MD", START)
    rows = {r["sprint_id"]: r for r in result["rows"]}
    assert rows[11] == {"sprint_id": 11, "tested": 2, "failed": 1, "fail_rate": 0.5, "failed_keys": ["MD-2"],
                        "sub_bugs_on_tested": 1, "sub_bugs_per_story": 0.5}
    assert rows[12]["tested"] == 1 and rows[12]["failed"] == 1 and rows[12]["fail_rate"] == 1.0
    assert rows[13]["tested"] == 0 and rows[13]["fail_rate"] is None and rows[13]["sub_bugs_per_story"] is None
    assert result["unsprinted_tested"] == 1


def test_key_order_sorts_by_ticket_number():
    assert sorted(["MD-100", "MD-99", "MD-7"], key=qa.key_order) == ["MD-7", "MD-99", "MD-100"]


TZ = ZoneInfo("America/New_York")


def _escape_seed(conn):
    ticket(conn, 1, "Defect", "2026-06-05T00:00:00Z", [S1])
    ticket(conn, 2, "Bug", "2026-06-06T00:00:00Z", [S1])
    ticket(conn, 3, "Sub-bug", "2026-06-07T00:00:00Z", [S1])
    ticket(conn, 4, "Story", "2026-06-05T00:00:00Z", [S1])
    ticket(conn, 5, "Bug", "2026-06-20T00:00:00Z", [S2])
    ticket(conn, 6, "Defect", "2026-07-01T02:00:00Z", [S3])  # 1 July UTC is still 30 June in New York
    ticket(conn, 7, "Defect", "2026-06-05T00:00:00Z", [C3S], project="C3")


def test_escape_rate_by_sprint_uses_creation_inside_the_sprint_dates(conn):
    _escape_seed(conn)
    sprints = qa.list_sprints(conn, "MD", START, TODAY)
    rows = {r["sprint_id"]: r for r in qa.escape_rate_by_sprint(conn, sprints, "MD")}
    assert rows[11] == {"sprint_id": 11, "defects": 1, "bugs": 1, "sub_bugs": 1, "found": 3,
                        "escape_rate": 1 / 3, "defect_keys": ["MD-1"]}
    assert rows[12]["found"] == 1 and rows[12]["escape_rate"] == 0.0
    assert rows[13]["defects"] == 1 and rows[13]["escape_rate"] == 1.0


def test_escape_rate_by_month_uses_report_time_zone(conn):
    _escape_seed(conn)
    rows = qa.escape_rate_by_month(conn, "MD", START, TODAY, TZ)
    assert [r["month"] for r in rows] == ["2026-06", "2026-07"]
    assert rows[0]["defects"] == 2 and rows[0]["found"] == 5 and rows[0]["defect_keys"] == ["MD-1", "MD-6"]
    assert rows[1]["found"] == 0 and rows[1]["escape_rate"] is None
