import pytest

from delivery_analysis.connectors.jira import connector as jcn
from delivery_analysis.connectors.jira.client import JiraClient
from delivery_analysis.connectors.jira.jql import jql_date
from delivery_analysis.connectors.jira.statuses import SEED
from delivery_analysis.store import db
from delivery_analysis.store import project_selection as ps
from delivery_analysis.sync.runner import run_sync, shift_cursor, utc_now_iso
from zoneinfo import ZoneInfo

from jira_fakes import FakeJira, history, issue, jira_ts, user

NOW = "2026-10-15T12:00:00Z"
EMAIL = "me@corp.example"
TOKEN = "tok-jira-LEAK-1"
ANN = user("acc-ann", "Ann Example", "ann@corp.example")
BOB = user("acc-bob", "Bob Builder")


def fake_api(**kwargs):
    api = FakeJira(email=EMAIL, token=TOKEN, **kwargs)
    api.add_project("MD", 10001, "Move Docs", list(SEED))
    return api


def build(tmp_path, api, *, budget=600, select=True, window_days=90, now=lambda: "2026-10-15T12:00:00Z"):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    if select:
        ps.add_project(conn, "jira", "MD", "10001", "Move Docs", "customfield_10004", NOW)
        ps.seed_statuses(conn, "jira", "MD", SEED)
    client = JiraClient(EMAIL, TOKEN, transport=api.transport(), sleep=lambda s: None, budget=budget)
    return conn, jcn.JiraConnector(client, path, window_days=window_days, now=now), client


def md_result(results):
    """The MD project's result; the developers scope also runs and is covered in test_jira_developer_scope."""
    return next(r for r in results if r.scope == "MD")


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def populate(api):
    api.add_issue(
        issue(1001, "MD-1", status="COMPLETED", assignee=ANN, reporter=BOB, points=5, updated="2026-10-10T10:00:00.000-0700"),
        [history(1, "2026-10-02T10:00:00Z", "To Do", "In Progress"), history(2, "2026-10-09T10:00:00Z", "In Progress", "COMPLETED")],
    )
    api.add_issue(issue(1002, "MD-2", status="To Do", updated="2026-10-11T10:00:00.000-0700"))
    api.add_issue(
        issue(1003, "MD-3", status="DISREGARD", assignee=BOB, updated="2026-10-12T10:00:00.000-0700"),
        [history(3, "2026-10-03T10:00:00Z", "To Do", "DISREGARD")],
    )


def test_validate_does_no_network_without_projects_or_without_an_email(tmp_path):
    api = fake_api()
    conn, connector, client = build(tmp_path, api, select=False)
    assert connector.validate() == [] and api.requests == []
    conn2, connector2, client2 = build(tmp_path / "x", api)  # selected, but the client has no email
    client2.email = ""
    assert "ATLASSIAN_EMAIL" in connector2.validate()[0] and api.requests == []


def test_validate_checks_myself_and_explains_failures(tmp_path):
    api = fake_api()
    conn, connector, _ = build(tmp_path, api)
    assert connector.validate() == []
    assert [path for _, path, _ in api.requests] == ["/rest/api/3/myself"]
    api.errors["/myself"] = 401
    message = connector.validate()[0]
    assert "rejected the email or token" in message and TOKEN not in message and EMAIL not in message
    api.errors["/myself"] = 403
    assert "read:jira-user" in connector.validate()[0]
    api.errors["/myself"] = 404
    assert "JIRA_BASE_URL" in connector.validate()[0]
    del api.errors["/myself"]
    api.myself_empty = True
    assert "JIRA_BASE_URL" in connector.validate()[0]


def test_scopes_are_the_selected_project_keys(tmp_path):
    api = fake_api()
    conn, connector, _ = build(tmp_path, api)
    ps.add_project(conn, "jira", "AA", "2", "Aye", None, NOW)
    assert connector.scopes() == ["AA", "MD", "developers"]


def test_a_full_sync_writes_issues_history_identities_links_and_properties(tmp_path):
    api = fake_api()
    populate(api)
    conn, connector, _ = build(tmp_path, api)
    result = md_result(run_sync(conn, [connector], now=lambda: NOW))
    assert (result.status, result.records > 0) == ("ok", True)
    items = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM work_item")}
    assert items["MD-1"]["status_category"] == "done"
    assert (items["MD-1"]["started_at"], items["MD-1"]["resolved_at"], items["MD-1"]["story_points"]) == (
        "2026-10-02T10:00:00Z", "2026-10-09T10:00:00Z", 5.0
    )
    assert items["MD-3"]["status_category"] == "dropped" and items["MD-3"]["resolved_at"] is None
    assert items["MD-2"]["story_points"] is None
    assert count(conn, "work_item_transition") == 3
    assert {r["account_id"] for r in conn.execute("SELECT account_id FROM identity WHERE source='jira'")} == {"acc-ann", "acc-bob"}
    assert conn.execute("SELECT value FROM property WHERE record_kind='identity' AND record_id='jira:acc-ann' AND name='email'").fetchone()["value"] == "ann@corp.example"
    assert count(conn, "raw_payload") == 3
    cursor = conn.execute("SELECT cursor FROM sync_state WHERE connector='jira' AND scope='MD'").fetchone()["cursor"]
    assert cursor == "2026-10-12T17:00:00Z"
    assert 'project = "MD"' in api.jqls[0]


def test_each_search_page_is_one_batch_with_an_advancing_cursor(tmp_path):
    api = fake_api(page_size=2)
    for number in range(1, 6):
        api.add_issue(issue(2000 + number, f"MD-{number}", updated=f"2026-10-0{number}T10:00:00.000-0700"))
    conn, connector, client = build(tmp_path, api)
    batches = list(connector.sync("MD", None))
    assert len(batches) == 3 and all(b.records for b in batches)
    assert [b.cursor for b in batches] == ["2026-10-02T17:00:00Z", "2026-10-04T17:00:00Z", "2026-10-05T17:00:00Z"]
    assert api.count("/search/jql") == 3


def test_an_issue_whose_history_spans_two_bulkfetch_pages_is_stored_once_and_whole(tmp_path):
    api = fake_api(history_page=2)
    api.add_issue(
        issue(1001, "MD-1", status="COMPLETED", assignee=ANN),
        [history(1, "2026-10-02T10:00:00Z", "To Do", "In Progress"),
         history(2, "2026-10-03T10:00:00Z", "In Progress", "COMPLETED"),
         history(3, "2026-10-04T10:00:00Z", "COMPLETED", "In Progress"),
         history(4, "2026-10-05T10:00:00Z", "In Progress", "COMPLETED")],
    )
    conn, connector, _ = build(tmp_path, api)
    result = md_result(run_sync(conn, [connector], now=lambda: NOW))
    assert result.status == "ok"
    assert api.count("/changelog/bulkfetch") == 2
    assert count(conn, "work_item_transition") == 4
    item = conn.execute("SELECT started_at, resolved_at FROM work_item").fetchone()
    assert (item["started_at"], item["resolved_at"]) == ("2026-10-02T10:00:00Z", "2026-10-05T10:00:00Z")
    assert conn.execute("SELECT value FROM property WHERE name='reopen_count'").fetchone()["value"] == "1"


def test_a_second_sync_changes_nothing_and_reads_from_the_cursor_minus_the_overlap(tmp_path):
    api = fake_api()
    populate(api)
    conn, connector, _ = build(tmp_path, api)
    run_sync(conn, [connector], now=lambda: NOW)
    before = {t: count(conn, t) for t in ("work_item", "work_item_transition", "property", "identity", "link", "raw_payload")}
    snapshot = [tuple(r) for r in conn.execute("SELECT source_id, status, started_at, resolved_at FROM work_item ORDER BY source_id")]
    run_sync(conn, [connector], now=lambda: NOW)
    assert {t: count(conn, t) for t in before} == before
    assert [tuple(r) for r in conn.execute("SELECT source_id, status, started_at, resolved_at FROM work_item ORDER BY source_id")] == snapshot
    expected = jql_date(shift_cursor("2026-10-12T17:00:00Z", 2 / 24), ZoneInfo("America/Los_Angeles"))
    assert expected in api.jqls[-1]


def test_the_first_sync_is_limited_to_the_window(tmp_path):
    api = fake_api()
    populate(api)
    conn, connector, _ = build(tmp_path, api, window_days=30)
    list(connector.sync("MD", None))
    assert "2026/09/15 05:00" in api.jqls[0]


def test_an_unmapped_current_status_fails_before_any_search_or_write(tmp_path):
    api = fake_api()
    api.projects["MD"]["statuses"] = list(SEED) + ["Brand New"]
    populate(api)
    conn, connector, _ = build(tmp_path, api)
    result = md_result(run_sync(conn, [connector], now=lambda: NOW))
    assert result.status == "failed"
    assert "Brand New" in result.error and 'projects map jira:MD "<status>"' in result.error
    assert count(conn, "work_item") == 0 and api.count("/search/jql") == 0


def test_an_unknown_name_in_old_history_is_remembered_not_fatal(tmp_path):
    api = fake_api()
    api.add_issue(issue(1, "MD-1", status="In Progress"), [history(1, "2026-10-02T10:00:00Z", "Retired Status", "In Progress")])
    conn, connector, _ = build(tmp_path, api)
    result = md_result(run_sync(conn, [connector], now=lambda: NOW))
    assert result.status == "ok" and connector.unknown_statuses == {"Retired Status"}


def test_the_request_budget_ends_the_project_cleanly_and_the_next_sync_continues(tmp_path):
    api = fake_api(page_size=1)
    for number in range(1, 4):
        api.add_issue(issue(3000 + number, f"MD-{number}", updated=f"2026-10-0{number}T10:00:00.000-0700"))
    conn, connector, client = build(tmp_path, api, budget=7)
    result = md_result(run_sync(conn, [connector], now=lambda: NOW))
    assert result.status == "ok"
    done = count(conn, "work_item")
    assert 0 < done < 3
    client.budget = 600
    run_sync(conn, [connector], now=lambda: NOW)
    assert count(conn, "work_item") == 3


def test_a_quota_stop_fails_the_project_and_keeps_earlier_pages(tmp_path):
    api = fake_api(page_size=1)
    for number in range(1, 3):
        api.add_issue(issue(3000 + number, f"MD-{number}", updated=f"2026-10-0{number}T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    original = api._search
    calls = []

    def flaky(body):
        calls.append(1)
        if len(calls) == 2:
            import httpx
            return httpx.Response(429, headers={"RateLimit-Reason": "jira-quota-tenant-based"})
        return original(body)

    api._search = flaky
    result = md_result(run_sync(conn, [connector], now=lambda: NOW))
    assert result.status == "failed" and "quota" in result.error
    assert count(conn, "work_item") == 1


def test_a_malformed_timestamp_fails_the_page_and_writes_nothing_from_it(tmp_path):
    api = fake_api()
    api.add_issue(issue(1, "MD-1", created="someday"))
    conn, connector, _ = build(tmp_path, api)
    result = md_result(run_sync(conn, [connector], now=lambda: NOW))
    assert result.status == "failed" and count(conn, "work_item") == 0


def test_a_person_mapped_by_hand_stays_mapped_after_a_sync(tmp_path):
    api = fake_api()
    populate(api)
    conn, connector, _ = build(tmp_path, api)
    conn.execute("INSERT INTO person (person_id, display_name) VALUES ('p-ann', 'Ann Example')")
    conn.execute("INSERT INTO identity (source, account_id, person_id, label, manual) VALUES ('jira', 'acc-ann', 'p-ann', 'old label', 1)")
    run_sync(conn, [connector], now=lambda: NOW)
    row = conn.execute("SELECT person_id, label, manual FROM identity WHERE source='jira' AND account_id='acc-ann'").fetchone()
    assert (row["person_id"], row["label"], row["manual"]) == ("p-ann", "Ann Example", 1)


def test_syncing_an_unselected_project_is_a_plain_error(tmp_path):
    api = fake_api()
    conn, connector, _ = build(tmp_path, api)
    with pytest.raises(jcn.JiraError, match="projects add jira:ZZ"):
        list(connector.sync("ZZ", None))


def test_recent_dates_in_the_live_offset_form_sync_with_the_real_clock(tmp_path):
    api = fake_api()
    api.add_issue(issue(1, "MD-1", updated=jira_ts(2), created=jira_ts(5)))
    conn, connector, _ = build(tmp_path, api, now=utc_now_iso)
    result = md_result(run_sync(conn, [connector]))
    assert result.status == "ok"
