import pytest

from bitbucket_fakes import FakeBitbucket, commit, pr, recent
from delivery_analysis.connectors.bitbucket.client import BitbucketClient, BitbucketError
from delivery_analysis.connectors.bitbucket.connector import BitbucketConnector
from delivery_analysis.store import db, repo_selection, sync_state
from delivery_analysis.sync.runner import run_sync

UUID_A = "{11111111-1111-1111-1111-111111111111}"
UUID_B = "{22222222-2222-2222-2222-222222222222}"
NOW = "2026-10-15T00:00:00Z"
ANN = "Ann Example <ann@corp.example>"
BOB = "Bob Builder <bob@corp.example>"


def setup(tmp_path, fake, repos, budget=900, window_days=90):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    for slug, uuid in repos:
        repo_selection.add_repo(conn, "bitbucket", uuid, fake.workspace, slug, NOW)
    client = BitbucketClient(fake.token, transport=fake.transport(), sleep=lambda s: None, budget=budget)
    return conn, BitbucketConnector(client, path, window_days=window_days)


def rows(conn, sql, *params):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def test_scopes_are_the_selected_uuids(tmp_path):
    fake = FakeBitbucket()
    conn, connector = setup(tmp_path, fake, [("b", UUID_B), ("a", UUID_A)])
    assert connector.scopes() == sorted([UUID_A, UUID_B])


def test_unfinished_repositories_come_first(tmp_path):
    uuid_c = "{33333333-3333-3333-3333-333333333333}"
    conn, connector = setup(tmp_path, FakeBitbucket(), [("a", UUID_A), ("b", UUID_B), ("c", uuid_c)])
    sync_state.set_cursor(conn, "bitbucket", UUID_A, "2026-10-14T00:00:00Z")
    sync_state.set_cursor(conn, "bitbucket", uuid_c, "2026-10-01T00:00:00Z")
    # B was cut short (no cursor) so it goes first; then the oldest cursor.
    assert connector.scopes() == [UUID_B, uuid_c, UUID_A]


def test_syncing_an_unselected_scope_is_an_error(tmp_path):
    conn, connector = setup(tmp_path, FakeBitbucket(), [])
    with pytest.raises(BitbucketError, match="not selected"):
        list(connector.sync("{nope}", None))


def test_validate_passes_with_a_good_token_and_scopes(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A)
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    assert connector.validate() == []


def test_validate_explains_each_failure(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A)
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    bad = BitbucketConnector(
        BitbucketClient("wrong", transport=fake.transport(), sleep=lambda s: None), tmp_path / "d.sqlite"
    )
    assert "rejected the token" in bad.validate()[0]
    fake.errors["/repositories/keyhealthtech"] = 403
    assert "read:repository:bitbucket" in connector.validate()[0]
    del fake.errors["/repositories/keyhealthtech"]
    fake.pr_scope_missing = True
    assert "read:pullrequest:bitbucket" in connector.validate()[0]


def test_validate_names_a_workspace_that_is_not_visible(tmp_path):
    fake = FakeBitbucket()
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    repo_selection.add_repo(conn, "bitbucket", UUID_A, "otherspace", "a", NOW)
    client = BitbucketClient(fake.token, transport=fake.transport(), sleep=lambda s: None)
    problems = BitbucketConnector(client, path).validate()
    assert "otherspace" in problems[0] and "not found" in problems[0]


def test_a_first_sync_stores_the_repository_commits_and_pull_requests(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo(
        "movedocs_v1.0", UUID_A,
        commits=[commit("h1", ANN, recent(1), account="acc-ann"), commit("h2", BOB, recent(2))],
        prs=[pr(1, "MERGED", recent(1)), pr(2, "OPEN", recent(2))],
    )
    # budget 5 = validate 2 + repository + commits + list, so detail does not run
    conn, connector = setup(tmp_path, fake, [("movedocs_v1.0", UUID_A)], budget=5)
    results = run_sync(conn, [connector])
    assert [(r.connector, r.scope, r.status) for r in results] == [("bitbucket", UUID_A, "ok")]
    repo = rows(conn, "SELECT source_id, workspace, name, default_branch FROM repository")
    assert repo == [{"source_id": UUID_A, "workspace": "keyhealthtech", "name": "movedocs_v1.0", "default_branch": "main"}]
    commits = {r["sha"]: r for r in rows(conn, "SELECT sha, author_account, author_name, author_email FROM vcs_commit")}
    assert commits["h1"]["author_email"] == "ann@corp.example" and commits["h1"]["author_account"] == "acc-ann"
    assert commits["h2"]["author_account"] is None and commits["h2"]["author_name"] == "Bob Builder"
    prs = {r["number"]: r for r in rows(conn, "SELECT number, state, branch, title FROM change_request")}
    assert prs["1"]["state"] == "MERGED" and prs["2"]["state"] == "OPEN"
    assert sync_state.get_cursor(conn, "bitbucket", UUID_A).endswith("Z")
    kinds = {r["kind"] for r in rows(conn, "SELECT kind FROM raw_payload")}
    assert kinds == {"repository", "commit", "pull_request"}


def test_the_commit_walk_stops_after_a_full_page_older_than_the_window(tmp_path):
    fake = FakeBitbucket()
    commits = [commit(f"r{i}", ANN, recent(1)) for i in range(5)] + [
        commit(f"o{i}", ANN, recent(200)) for i in range(300)
    ]
    fake.add_repo("a", UUID_A, commits=commits)
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector])
    assert fake.count("/commits") == 2  # the second page is all old, so the third is never requested
    assert len(rows(conn, "SELECT sha FROM vcs_commit")) == 5


def test_an_old_commit_before_newer_ones_does_not_stop_the_walk(tmp_path):
    fake = FakeBitbucket()
    commits = [commit("old", ANN, recent(200))] + [commit(f"r{i}", ANN, recent(1)) for i in range(150)]
    fake.add_repo("a", UUID_A, commits=commits)
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector])
    assert fake.count("/commits") == 2
    assert len(rows(conn, "SELECT sha FROM vcs_commit")) == 150


def test_the_pull_request_list_asks_for_all_states_and_stops_at_the_window(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A, prs=[pr(1, "OPEN", recent(1)), pr(2, "MERGED", recent(5)), pr(3, "MERGED", recent(300))])
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector])
    pr_requests = [params for path, params in fake.requests if path.endswith("/pullrequests") and "state" in params]
    assert pr_requests[0]["state"] == ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
    assert pr_requests[0]["sort"] == ["-updated_on"]
    assert sorted(r["number"] for r in rows(conn, "SELECT number FROM change_request")) == ["1", "2"]


def test_a_merged_pull_request_gets_an_approximate_merge_time_before_detail(tmp_path):
    fake = FakeBitbucket()
    updated = recent(2)
    fake.add_repo("a", UUID_A, prs=[pr(1, "MERGED", updated)])
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)], budget=5)  # no budget left for detail
    run_sync(conn, [connector])
    row = rows(conn, "SELECT merged_at, closed_at FROM change_request")[0]
    assert row["merged_at"] == row["closed_at"] and row["merged_at"].endswith("Z")
    props = {(r["name"], r["value"]) for r in rows(conn, "SELECT name, value FROM property WHERE record_kind = 'change_request'")}
    assert ("times_from", "updated_on") in props


def test_assigned_reviewers_are_stored_and_requested_in_the_list_fields(tmp_path):
    fake = FakeBitbucket()
    with_reviewers = pr(1, "OPEN", recent(1))
    with_reviewers["participants"] = [
        {"role": "REVIEWER", "approved": False, "user": {"account_id": "acc-bob"}},
        {"role": "REVIEWER", "approved": True, "user": {"account_id": "acc-cy"}},
    ]
    fake.add_repo("a", UUID_A, prs=[with_reviewers])
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector])
    props = {r["name"]: r["value"] for r in rows(conn, "SELECT name, value FROM property WHERE name LIKE 'reviewer:%'")}
    assert props == {"reviewer:acc-bob": "pending", "reviewer:acc-cy": "approved"}
    listing = [params for path, params in fake.requests if path.endswith("/pullrequests") and "state" in params][0]
    assert "values.participants.role" in listing["fields"][0]


def test_blank_and_unmapped_authors_are_stored_as_empty(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A, commits=[commit("h1", "Build Bot <>", recent(1)), commit("h2", "noreply@corp.example", recent(1))])
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector])
    got = {r["sha"]: (r["author_name"], r["author_email"], r["author_account"]) for r in rows(conn, "SELECT sha, author_name, author_email, author_account FROM vcs_commit")}
    assert got == {"h1": ("Build Bot", None, None), "h2": (None, "noreply@corp.example", None)}


def test_a_second_sync_adds_nothing_new(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A, commits=[commit("h1", ANN, recent(1))], prs=[pr(1, "OPEN", recent(1))])
    conn, connector = setup(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector])
    tables = ("vcs_commit", "change_request", "property", "raw_payload")
    first = [rows(conn, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in tables]
    _, again = setup(tmp_path, fake, [])
    run_sync(conn, [again])
    second = [rows(conn, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in tables]
    assert first == second


def test_one_failing_repository_does_not_stop_the_other(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A, commits=[commit("ha", ANN, recent(1))])
    fake.add_repo("b", UUID_B, commits=[commit("hb", BOB, recent(1))])
    fake.errors[UUID_A + "/commits"] = 403
    conn, connector = setup(tmp_path, fake, [("a", UUID_A), ("b", UUID_B)])
    results = {r.scope: r for r in run_sync(conn, [connector])}
    assert results[UUID_A].status == "failed" and "lacks permission" in results[UUID_A].error
    assert results[UUID_B].status == "ok"
    assert [r["sha"] for r in rows(conn, "SELECT sha FROM vcs_commit")] == ["hb"]
    stale = {(s["connector"], s["scope"]): s["stale"] for s in sync_state.list_sync_states(conn)}
    assert stale[("bitbucket", UUID_A)] is True and stale[("bitbucket", UUID_B)] is False
