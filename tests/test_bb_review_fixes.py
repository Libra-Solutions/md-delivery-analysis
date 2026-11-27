from delivery_analysis.core.time_utils import to_utc_iso
from bitbucket_fakes import FakeBitbucket, comment, commit, pr, recent, update
from delivery_analysis.connectors.bitbucket.client import BitbucketClient
from delivery_analysis.connectors.bitbucket.connector import BitbucketConnector
from delivery_analysis.store import db, repo_selection, sync_state
from delivery_analysis.sync.runner import run_sync

UUID_A = "{11111111-1111-1111-1111-111111111111}"
UUID_B = "{22222222-2222-2222-2222-222222222222}"
NOW = "2026-10-15T00:00:00Z"
ANN = "Ann Example <ann@corp.example>"


def build(tmp_path, fake, repos):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    for slug, uuid in repos:
        repo_selection.add_repo(conn, "bitbucket", uuid, fake.workspace, slug, NOW)
    return conn, path


def connector_for(path, fake, budget=900):
    client = BitbucketClient(fake.token, transport=fake.transport(), sleep=lambda s: None, budget=budget)
    return BitbucketConnector(client, path, window_days=90)


def rows(conn, sql, *params):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def busy_repo(fake, slug, uuid, prs=6):
    fake.add_repo(
        slug, uuid,
        commits=[commit(f"c-{slug}", ANN, recent(1))],
        prs=[pr(n, "OPEN", recent(1 + n / 10)) for n in range(1, prs + 1)],
        activity={n: [comment(n, recent(1))] for n in range(1, prs + 1)},
    )


def test_one_repos_detail_backlog_cannot_starve_the_next_repo(tmp_path):
    fake = FakeBitbucket()
    busy_repo(fake, "a", UUID_A, prs=30)
    busy_repo(fake, "b", UUID_B)
    conn, path = build(tmp_path, fake, [("a", UUID_A), ("b", UUID_B)])
    results = {r.scope: r for r in run_sync(conn, [connector_for(path, fake, budget=40)])}
    assert results[UUID_A].status == "ok" and results[UUID_B].status == "ok"
    assert rows(conn, "SELECT sha FROM vcs_commit WHERE repository_id = ?", UUID_B) == [{"sha": "c-b"}]


def test_running_out_of_budget_in_the_list_stage_ends_the_repo_quietly_without_a_cursor(tmp_path):
    fake = FakeBitbucket()
    busy_repo(fake, "a", UUID_A, prs=2)
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    results = run_sync(conn, [connector_for(path, fake, budget=4)])  # validate 2, repository 1, commits 1
    assert results[0].status == "ok"
    assert sync_state.get_cursor(conn, "bitbucket", UUID_A) is None


def test_a_late_pushed_commit_with_an_old_author_date_is_kept_on_a_later_run(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A, commits=[commit("h1", ANN, recent(1))])
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector_for(path, fake)])
    fake.repos["a"]["commits"].insert(0, commit("late", ANN, recent(20)))
    run_sync(conn, [connector_for(path, fake)])
    assert {r["sha"] for r in rows(conn, "SELECT sha FROM vcs_commit")} == {"h1", "late"}


def test_a_pull_request_merged_after_it_was_detailed_gets_an_approximate_merge_time(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A, prs=[pr(1, "OPEN", recent(3))], activity={1: [update("OPEN", recent(3))]})
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector_for(path, fake)])
    merged = pr(1, "MERGED", recent(0.05))  # after the last run, inside the re-sync margin
    fake.repos["a"]["prs"] = [merged]
    run_sync(conn, [connector_for(path, fake, budget=5)])  # no budget left for detail
    row = rows(conn, "SELECT state, merged_at, closed_at FROM change_request")[0]
    assert row["state"] == "MERGED" and row["merged_at"] is not None and row["closed_at"] is not None


def test_exact_times_from_activity_survive_a_later_list_pass(tmp_path):
    fake = FakeBitbucket()
    exact = recent(3)
    fake.add_repo("a", UUID_A, prs=[pr(1, "MERGED", recent(1))], activity={1: [update("MERGED", exact)]})
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    run_sync(conn, [connector_for(path, fake)])
    run_sync(conn, [connector_for(path, fake, budget=5)])
    stored = rows(conn, "SELECT merged_at FROM change_request")[0]["merged_at"]
    assert stored == to_utc_iso(exact)


def test_a_missing_commits_endpoint_keeps_the_activity_that_was_fetched(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo("a", UUID_A, prs=[pr(1, "MERGED", recent(1))], activity={1: [update("MERGED", recent(2))]})
    fake.errors["/pullrequests/1/commits"] = 404
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    results = run_sync(conn, [connector_for(path, fake)])
    assert results[0].status == "ok"
    assert [r["type"] for r in rows(conn, "SELECT type FROM change_event")] == ["merged"]
    assert repo_selection.detail_progress(conn, UUID_A) == (1, 1)


def test_a_server_error_on_one_pull_request_skips_it_and_does_not_fail_the_repo(tmp_path):
    fake = FakeBitbucket()
    busy_repo(fake, "a", UUID_A, prs=3)
    fake.errors["/pullrequests/2/diffstat"] = 500
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    results = run_sync(conn, [connector_for(path, fake)])
    assert results[0].status == "ok"
    assert repo_selection.detail_progress(conn, UUID_A) == (2, 3)


def test_a_rate_limit_during_detail_ends_the_stage_without_failing_the_repo(tmp_path):
    fake = FakeBitbucket()
    busy_repo(fake, "a", UUID_A, prs=3)
    fake.errors["/activity"] = 429
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    results = run_sync(conn, [connector_for(path, fake)])
    assert results[0].status == "ok"
    assert sync_state.get_cursor(conn, "bitbucket", UUID_A) is not None
    assert repo_selection.detail_progress(conn, UUID_A) == (0, 3)
    assert len(rows(conn, "SELECT sha FROM vcs_commit")) == 1


def test_when_every_pull_request_fails_detail_the_repo_fails_instead_of_silently_skipping(tmp_path):
    fake = FakeBitbucket()
    busy_repo(fake, "a", UUID_A, prs=3)
    fake.errors["/diffstat"] = 500
    conn, path = build(tmp_path, fake, [("a", UUID_A)])
    results = run_sync(conn, [connector_for(path, fake)])
    assert results[0].status == "failed" and "HTTP 500" in results[0].error
