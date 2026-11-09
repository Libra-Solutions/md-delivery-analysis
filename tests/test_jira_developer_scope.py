import pytest
from zoneinfo import ZoneInfo

from delivery_analysis.connectors.jira import connector as jcn
from delivery_analysis.connectors.jira.client import JiraClient
from delivery_analysis.connectors.jira.jql import developer_jql
from delivery_analysis.connectors.jira.statuses import SEED
from delivery_analysis.store import db
from delivery_analysis.store import project_selection as ps
from delivery_analysis.store.upsert import write_batch
from delivery_analysis.sync.runner import run_sync

from jira_fakes import FakeJira, history, issue, user

NOW = "2026-10-15T12:00:00Z"
EMAIL = "me@corp.example"
TOKEN = "tok-jira-LEAK-1"
DEV1, DEV2 = "customfield_12001", "customfield_12002"
LA = ZoneInfo("America/Los_Angeles")
ANN = user("acc-ann", "Ann Example")


def fake_api(**kwargs):
    api = FakeJira(email=EMAIL, token=TOKEN, **kwargs)
    api.add_project("MD", 10001, "Move Docs", list(SEED))
    api.add_dev_fields(DEV1, DEV2)
    return api


def build(tmp_path, api, *, select=True, members=("acc-ann",), budget=600):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    if select:
        ps.add_project(conn, "jira", "MD", "10001", "Move Docs", "customfield_10004", NOW)
        ps.seed_statuses(conn, "jira", "MD", SEED)
    for account in members:
        add_member(conn, account)
    client = JiraClient(EMAIL, TOKEN, transport=api.transport(), sleep=lambda s: None, budget=budget)
    return conn, jcn.JiraConnector(client, path, now=lambda: NOW), client


def add_member(conn, account, *, source="jira", status="active", team="t1"):
    person = f"p-{account}"
    conn.execute("INSERT OR IGNORE INTO person (person_id, display_name) VALUES (?, ?)", (person, account))
    conn.execute(
        "INSERT OR IGNORE INTO identity (source, account_id, person_id) VALUES (?, ?, ?)", (source, account, person)
    )
    conn.execute("INSERT OR IGNORE INTO team (team_id, name, created_at) VALUES (?, ?, ?)", (team, team, NOW))
    conn.execute(
        "INSERT OR IGNORE INTO team_member (team_id, person_id, status) VALUES (?, ?, ?)", (team, person, status)
    )
    conn.commit()


def store(conn, connector, scope, since=None):
    """Run one scope and write every batch, like the runner does."""
    batches = list(connector.sync(scope, since))
    for batch in batches:
        write_batch(conn, batch, NOW)
    conn.commit()
    return batches


def dev_issue(issue_id, key, project="OTH", dev1="acc-ann", dev2=None, **kwargs):
    extra = {DEV1: {"accountId": dev1} if dev1 else None, DEV2: {"accountId": dev2} if dev2 else None}
    return issue(issue_id, key, project=project, extra=extra, **kwargs)


def test_the_jql_text_is_exact_and_quoted():
    jql = developer_jql([DEV1, DEV2], ["acc-1", "712020:ab-c_d"], ["MD", "AA"], "2026-07-17T12:00:00Z", LA)
    assert jql == (
        '(cf[12001] in ("acc-1", "712020:ab-c_d") OR cf[12002] in ("acc-1", "712020:ab-c_d")) '
        'AND project not in ("MD", "AA") AND updated >= "2026/07/17 05:00" '
        "ORDER BY updated ASC, key ASC"
    )


@pytest.mark.parametrize(
    "fields,accounts,keys",
    [
        ([DEV1], ['a") OR 1=1 --'], ["MD"]),
        ([DEV1], ["a b"], ["MD"]),
        ([DEV1], [""], ["MD"]),
        ([DEV1], ["acc"], ['MD" OR x']),
        ([DEV1], ["acc"], ["1AB"]),
        (["customfield_1) OR (1"], ["acc"], ["MD"]),
        ([DEV1], [], ["MD"]),
        ([DEV1], ["acc"], []),
        ([], ["acc"], ["MD"]),
    ],
)
def test_the_jql_rejects_bad_ids_keys_and_empty_inputs(fields, accounts, keys):
    with pytest.raises(ValueError):
        developer_jql(fields, accounts, keys, "2026-07-17T12:00:00Z", LA)


def test_scopes_add_developers_only_when_a_project_is_selected(tmp_path):
    api = fake_api()
    conn, connector, _ = build(tmp_path, api, select=False)
    assert connector.scopes() == []
    conn2, connector2, _ = build(tmp_path / "x", api)
    assert connector2.scopes() == ["MD", "developers"]
    ps.add_project(conn2, "jira", "AA", "2", "Aye", None, NOW)
    assert connector2.scopes() == ["AA", "MD", "developers"]


def test_a_project_keyed_in_capitals_does_not_collide_with_the_pseudo_scope(tmp_path):
    api = fake_api()
    api.add_project("DEVELOPERS", 10002, "Devs", list(SEED))
    api.add_issue(issue(1, "DEVELOPERS-1", project="DEVELOPERS", updated="2026-10-10T10:00:00.000-0700"))
    api.add_issue(dev_issue(2, "OTH-1", updated="2026-10-10T10:00:00.000-0700", status="To Do"))
    conn, connector, _ = build(tmp_path, api)
    ps.add_project(conn, "jira", "DEVELOPERS", "10002", "Devs", "customfield_10004", NOW)
    ps.seed_statuses(conn, "jira", "DEVELOPERS", SEED)
    assert connector.name == "jira" and connector.scopes() == ["DEVELOPERS", "MD", "developers"]
    assert len({s for s in connector.scopes()}) == 3
    run_sync(conn, [connector], now=lambda: NOW)
    keys = {r["scope"] for r in conn.execute("SELECT scope FROM sync_state WHERE connector='jira'")}
    assert {"DEVELOPERS", "MD", "developers"} <= keys
    found = {r["key"] for r in conn.execute("SELECT key FROM work_item")}
    assert found == {"DEVELOPERS-1", "OTH-1"}


def test_the_sync_queries_only_active_team_member_accounts_and_excludes_selected_projects(tmp_path):
    api = fake_api()
    conn, connector, _ = build(tmp_path, api, members=("acc-ann",))
    add_member(conn, "acc-bob", status="inactive", team="t2")
    add_member(conn, "acc-cy", status="excluded", team="t3")
    add_member(conn, "acc-dee", source="github", team="t4")
    add_member(conn, "bb-eve", source="bitbucket", team="t5")
    add_member(conn, "{uuid-with-braces}", source="bitbucket", team="t6")
    conn.execute("INSERT INTO identity (source, account_id) VALUES ('jira', 'acc-nobody')")
    conn.commit()
    ps.add_project(conn, "jira", "AA", "2", "Aye", None, NOW)
    store(conn, connector, "developers")
    (jql,) = api.jqls
    assert 'cf[12001] in ("acc-ann", "bb-eve")' in jql and 'cf[12002] in ("acc-ann", "bb-eve")' in jql
    for absent in ("acc-bob", "acc-cy", "acc-dee", "acc-nobody", "{"):
        assert absent not in jql
    assert 'project not in ("AA", "MD")' in jql
    assert 'updated >= "2026/07/17 05:00"' in jql and jql.endswith("ORDER BY updated ASC, key ASC")


def test_issues_keep_their_own_project_and_a_selected_project_never_appears(tmp_path):
    api = fake_api()
    api.add_issue(dev_issue(1, "OTH-1", status="COMPLETED", updated="2026-10-10T10:00:00.000-0700"))
    api.add_issue(dev_issue(2, "MD-9", project="MD", updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    rows = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM work_item")}
    assert set(rows) == {"OTH-1"} and rows["OTH-1"]["project"] == "OTH"
    assert rows["OTH-1"]["status_category"] == "done"


def test_the_code_guard_skips_a_selected_project_issue_even_if_jira_returns_it(tmp_path):
    api = fake_api()
    api.add_issue(dev_issue(1, "OTH-1", updated="2026-10-10T10:00:00.000-0700"))
    api.add_issue(dev_issue(2, "MD-9", project="MD", updated="2026-10-11T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    original = api._developer_pool
    api._developer_pool = lambda jql: list(api.issues)
    try:
        batches = store(conn, connector, "developers")
    finally:
        api._developer_pool = original
    assert {r["key"] for r in conn.execute("SELECT key FROM work_item")} == {"OTH-1"}
    assert len(batches) == 1


def test_dev_credit_properties_are_stored(tmp_path):
    api = fake_api()
    api.add_issue(dev_issue(1, "OTH-1", dev1="acc-ann", dev2="acc-ann", updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    names = {r["name"] for r in conn.execute("SELECT name FROM property WHERE record_kind='work_item'")}
    assert {"dev1_12001", "dev2_12002", "counts_for_impact"} <= names


def test_default_status_mapping_follows_the_seed_by_name(tmp_path):
    api = fake_api()
    for number, status in enumerate(["Backlog", "In Progress", "Dev Done", "Code Review", "COMPLETED", "DISREGARD"], 1):
        api.add_issue(dev_issue(number, f"OTH-{number}", status=status, updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    got = {r["status"]: r["status_category"] for r in conn.execute("SELECT status, status_category FROM work_item")}
    assert got == {name: SEED[name] for name in got} and len(got) == 6
    assert connector.unknown_statuses == set()


def test_unknown_statuses_are_reported_and_stored_as_todo(tmp_path):
    api = fake_api()
    api.add_issue(
        dev_issue(1, "OTH-1", status="Weird Now", updated="2026-10-10T10:00:00.000-0700"),
        [history(1, "2026-10-02T10:00:00Z", "To Do", "Old Odd"), history(2, "2026-10-03T10:00:00Z", "Old Odd", "Weird Now")],
    )
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    row = conn.execute("SELECT status_category, resolved_at FROM work_item WHERE key='OTH-1'").fetchone()
    assert (row["status_category"], row["resolved_at"]) == ("todo", None)
    assert connector.unknown_statuses == {"Weird Now", "Old Odd"}
    assert conn.execute("SELECT COUNT(*) AS n FROM work_item_transition").fetchone()["n"] == 2


def test_history_is_stored_with_the_mapped_statuses(tmp_path):
    api = fake_api()
    api.add_issue(
        dev_issue(1, "OTH-1", status="COMPLETED", updated="2026-10-10T10:00:00.000-0700"),
        [history(1, "2026-10-02T10:00:00Z", "To Do", "In Progress"), history(2, "2026-10-09T10:00:00Z", "In Progress", "COMPLETED")],
    )
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    row = conn.execute("SELECT started_at, resolved_at FROM work_item").fetchone()
    assert (row["started_at"], row["resolved_at"]) == ("2026-10-02T10:00:00Z", "2026-10-09T10:00:00Z")


def test_story_points_use_the_selected_projects_field_then_the_site_estimate_field(tmp_path):
    api = fake_api()
    api.add_issue(dev_issue(1, "OTH-1", points=5, updated="2026-10-10T10:00:00.000-0700"))
    api.add_issue(
        dev_issue(2, "OTH-2", points=None, points_field="customfield_11168", updated="2026-10-11T10:00:00.000-0700")
    )
    api.add_issue(
        dev_issue(3, "OTH-3", points=None, points_field="customfield_11104", updated="2026-10-12T10:00:00.000-0700")
    )
    api.add_issue(dev_issue(4, "OTH-4", points=None, updated="2026-10-13T10:00:00.000-0700"))
    api.issues[1]["fields"]["customfield_11168"] = 3
    api.issues[2]["fields"]["customfield_11104"] = 2
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    got = {r["key"]: r["story_points"] for r in conn.execute("SELECT key, story_points FROM work_item")}
    assert got == {"OTH-1": 5.0, "OTH-2": 3.0, "OTH-3": 2.0, "OTH-4": None}


def test_epics_and_initiatives_do_not_count_for_impact(tmp_path):
    api = fake_api()
    api.add_issue(dev_issue(1, "OTH-1", type="Epic", updated="2026-10-10T10:00:00.000-0700"))
    api.add_issue(dev_issue(2, "OTH-2", type="Story", updated="2026-10-11T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    got = {
        r["record_id"]: r["value"]
        for r in conn.execute("SELECT record_id, value FROM property WHERE name='counts_for_impact'")
    }
    assert got == {"1": "0", "2": "1"}


def test_no_team_members_means_no_batches_no_search_and_a_plain_message(tmp_path):
    api = fake_api()
    conn, connector, _ = build(tmp_path, api, members=())
    assert store(conn, connector, "developers") == []
    assert api.jqls == [] and api.count("/search/jql") == 0
    assert any("team" in note.lower() for note in connector.notices)
    results = run_sync(conn, [connector], now=lambda: NOW)
    assert {(r.scope, r.status) for r in results} == {("MD", "ok"), ("developers", "ok")}


def test_no_dev_fields_on_the_site_means_no_batches_and_a_plain_message(tmp_path):
    api = fake_api()
    api.fields = [f for f in api.fields if f["name"] not in ("Dev1", "Dev2")]
    api.add_issue(dev_issue(1, "OTH-1", updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    assert store(conn, connector, "developers") == []
    assert api.jqls == []
    assert any("Dev1" in note for note in connector.notices)
    results = run_sync(conn, [connector], now=lambda: NOW)
    assert {r.status for r in results} == {"ok"}


def test_tickets_where_a_member_is_qa1_or_qa2_are_fetched_too(tmp_path):
    api = fake_api()
    qa1, qa2 = "customfield_12003", "customfield_12004"
    for field_id, name in ((qa1, "QA1"), (qa2, "QA 2")):
        api.fields.append({"id": field_id, "name": name, "custom": True, "schema": {"type": "user"}})
    api.add_issue(issue(1, "OTH-1", project="OTH", extra={qa2: {"accountId": "acc-ann"}},
                        updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    assert "cf[12003]" in api.jqls[0] and "cf[12004]" in api.jqls[0]
    assert {r["key"] for r in conn.execute("SELECT key FROM work_item")} == {"OTH-1"}


def test_a_site_with_only_dev2_queries_that_field(tmp_path):
    api = fake_api()
    api.fields = [f for f in api.fields if f["name"] != "Dev1"]
    api.add_issue(dev_issue(1, "OTH-1", dev1=None, dev2="acc-ann", updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "developers")
    assert "cf[12001]" not in api.jqls[0] and "cf[12002]" in api.jqls[0]
    assert {r["key"] for r in conn.execute("SELECT key FROM work_item")} == {"OTH-1"}


def test_paging_and_the_cursor_advance_one_batch_per_page(tmp_path):
    api = fake_api(page_size=2)
    for number in range(1, 6):
        api.add_issue(dev_issue(100 + number, f"OTH-{number}", updated=f"2026-10-0{number}T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    batches = store(conn, connector, "developers")
    assert [b.cursor for b in batches] == ["2026-10-02T17:00:00Z", "2026-10-04T17:00:00Z", "2026-10-05T17:00:00Z"]
    assert api.count("/search/jql") == 3


def test_a_run_stores_the_developers_cursor_and_the_next_run_resumes_from_it(tmp_path):
    api = fake_api()
    api.add_issue(dev_issue(1, "OTH-1", updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    run_sync(conn, [connector], now=lambda: NOW)
    state = {
        r["scope"]: r["cursor"] for r in conn.execute("SELECT scope, cursor FROM sync_state WHERE connector='jira'")
    }
    assert state["developers"] == "2026-10-10T17:00:00Z"
    api.jqls.clear()
    run_sync(conn, [connector], now=lambda: NOW)
    assert any('updated >= "2026/10/03 10:00"' in jql for jql in api.jqls if "project not in" in jql)


def test_the_request_budget_ends_the_scope_cleanly(tmp_path):
    api = fake_api(page_size=1)
    for number in range(1, 4):
        api.add_issue(dev_issue(100 + number, f"OTH-{number}", updated=f"2026-10-0{number}T10:00:00.000-0700"))
    conn, connector, client = build(tmp_path, api, budget=5)
    batches = store(conn, connector, "developers")
    assert 0 < len(batches) < 3


def test_a_selected_projects_sync_is_unchanged(tmp_path):
    api = fake_api()
    api.add_issue(issue(1001, "MD-1", status="COMPLETED", assignee=ANN, points=5, updated="2026-10-10T10:00:00.000-0700"))
    api.add_issue(dev_issue(1, "OTH-1", updated="2026-10-10T10:00:00.000-0700"))
    conn, connector, _ = build(tmp_path, api)
    store(conn, connector, "MD")
    assert [r["key"] for r in conn.execute("SELECT key FROM work_item")] == ["MD-1"]
    assert 'project = "MD"' in api.jqls[0] and len(api.jqls) == 1
    assert conn.execute("SELECT story_points FROM work_item").fetchone()["story_points"] == 5.0


def test_syncing_developers_without_a_selected_project_is_a_plain_no_op(tmp_path):
    api = fake_api()
    conn, connector, _ = build(tmp_path, api, select=False)
    assert store(conn, connector, "developers") == []
    assert api.requests == []
