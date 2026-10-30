import json
from datetime import date
from zoneinfo import ZoneInfo

from qa_seed import C3S, S0, S1, S2, S3, link, move, qa_pass, seed_dashboard, ticket
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


def test_release_of_reads_the_version_from_regression_story_titles():
    assert qa.release_of("3.41 Regression") == "3.41"
    assert qa.release_of("  3.33 regression lite") == "3.33"
    assert qa.release_of("3.30 regression round 2") == "3.30"
    assert qa.release_of("MoveDocs UI Automation - Close Manual Regression Gap") is None
    assert qa.release_of("3.40 regressions found") is None
    assert qa.release_of(None) is None
    assert sorted(["3.10", "3.9"], key=qa.version_key) == ["3.9", "3.10"]


def test_regression_bugs_counts_every_bug_linked_to_the_release_stories(conn):
    r0 = ticket(conn, 1, "Story", "2026-05-22T00:00:00Z", summary="3.35 regression")
    r1 = ticket(conn, 2, "Story", "2026-06-10T00:00:00Z", summary="3.36 regression")
    r2 = ticket(conn, 3, "Story", "2026-06-20T00:00:00Z", summary="3.36 Regression round 2")
    r3 = ticket(conn, 4, "Story", "2026-07-01T00:00:00Z", summary="3.37 REGRESSION lite")
    ticket(conn, 5, "Story", "2026-06-10T00:00:00Z", summary="Add regression coverage")
    ticket(conn, 6, "Bug", "2026-06-11T00:00:00Z", summary="3.36 regression in login")
    b1 = ticket(conn, 7, "Bug", "2026-06-11T00:00:00Z")
    b2 = ticket(conn, 8, "Bug", "2026-06-21T00:00:00Z")
    b3 = ticket(conn, 9, "Bug", "2026-05-01T00:00:00Z")  # found before the story existed: still counts
    b4 = ticket(conn, 10, "Bug", "2026-06-12T00:00:00Z")
    story = ticket(conn, 11, "Story", "2026-07-02T00:00:00Z")
    old = ticket(conn, 12, "Bug", "2026-05-23T00:00:00Z")
    link(conn, r1, b1, "Block")
    link(conn, r2, b1, "Relates")       # same bug twice in one release counts once
    link(conn, b2, r2, "Relates")       # inward direction
    link(conn, r3, b3, "Blocks")
    link(conn, r3, story, "Relates")    # not a bug
    link(conn, r3, "99999", "Test")     # not synced
    link(conn, b4, r1, "parent")        # parent links are not regression links
    link(conn, r0, old, "Block")        # 3.35 regression started before the window
    rows = qa.regression_bugs_by_release(conn, "MD", START)
    assert rows == [
        {"release": "3.36", "regression_stories": ["MD-2", "MD-3"], "bugs": 2, "bug_keys": ["MD-7", "MD-8"],
         "in_progress": False},
        {"release": "3.37", "regression_stories": ["MD-4"], "bugs": 1, "bug_keys": ["MD-9"], "in_progress": True},
    ]


def test_dashboard_merges_sprint_rows_and_picks_closed_headlines(conn):
    seed_dashboard(conn)
    data = qa.qa_dashboard(conn, TODAY, TZ)
    assert data["project"] == "MD" and data["window"] == {"start": "2026-06-01", "end": "2026-07-20"}
    first = data["sprints"][0]
    assert first["name"] == "MD Sprint 1" and first["fail_rate"] == 0.5 and first["escape_rate"] == 0.5
    assert data["headline"]["sprint"]["name"] == "MD Sprint 2"
    assert data["headline"]["release"]["release"] == "3.36"
    assert [m["month"] for m in data["months"]] == ["2026-06", "2026-07"]
    assert "acc-tess" not in json.dumps(data)
