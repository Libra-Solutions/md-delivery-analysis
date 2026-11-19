from delivery_analysis.core.time_utils import to_utc_iso
from bitbucket_fakes import FakeBitbucket, approval, comment, commit, pr, recent, update
from delivery_analysis.connectors.bitbucket.client import BitbucketClient
from delivery_analysis.connectors.bitbucket.connector import BitbucketConnector
from delivery_analysis.store import db, repo_selection
from delivery_analysis.sync.runner import run_sync

UUID_A = "{11111111-1111-1111-1111-111111111111}"
NOW = "2026-10-15T00:00:00Z"
ANN = "Ann Example <ann@corp.example>"


def build(tmp_path, fake):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    repo_selection.add_repo(conn, "bitbucket", UUID_A, fake.workspace, "movedocs_v1.0", NOW)
    return conn, path


def connector_for(path, fake, budget=900):
    client = BitbucketClient(fake.token, transport=fake.transport(), sleep=lambda s: None, budget=budget)
    return BitbucketConnector(client, path, window_days=90)


def rows(conn, sql, *params):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


MERGED_AT = recent(3)  # clearly different from PR 3's updated_on (recent(1))


def standard(fake):
    """Three pull requests, newest first by updated_on: 3 (merged), 2 (open), 1 (declined)."""
    fake.add_repo(
        "movedocs_v1.0", UUID_A,
        commits=[commit("h1", ANN, recent(1)), commit("h2", ANN, recent(2))],
        prs=[pr(3, "MERGED", recent(1)), pr(2, "OPEN", recent(2)), pr(1, "DECLINED", recent(3))],
        activity={
            3: [update("OPEN", recent(4)), comment(31, recent(3)), comment(32, recent(3), deleted=True),
                approval(recent(2)), update("MERGED", MERGED_AT)],
            2: [comment(21, recent(2))],
            1: [update("DECLINED", recent(3))],
        },
        pr_commits={3: [{"hash": "h1"}, {"hash": "h2"}], 2: [{"hash": "h2"}], 1: []},
        diffstat={3: [{"status": "modified"}, {"status": "added"}], 2: [{"status": "modified"}], 1: []},
    )


def test_detail_fills_events_exact_times_counts_and_links(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    results = run_sync(conn, [connector_for(path, fake)])
    assert results[0].status == "ok"
    sid3 = f"{UUID_A}#3"
    events = rows(conn, "SELECT type FROM change_event WHERE change_request_id = ?", sid3)
    assert sorted(e["type"] for e in events) == ["approved", "comment", "merged", "update"]
    cr = rows(conn, "SELECT merged_at, closed_at, files_changed, commit_count FROM change_request WHERE source_id = ?", sid3)[0]
    assert cr["merged_at"] == cr["closed_at"] == to_utc_iso(MERGED_AT)
    assert (cr["files_changed"], cr["commit_count"]) == (2, 2)
    linked = {r["sha"] for r in rows(conn, "SELECT sha FROM vcs_commit WHERE change_request_id = ?", sid3)}
    assert "h1" in linked  # a commit in two pull requests is linked to the one detailed last
    props = {(r["record_id"], r["name"]): r["value"] for r in rows(conn, "SELECT record_id, name, value FROM property WHERE record_kind = 'change_request'")}
    assert props[(sid3, "times_from")] == "activity"
    assert props[(sid3, "detail_updated_on")] == props[(sid3, "updated_on")]
    declined = rows(conn, "SELECT merged_at, closed_at FROM change_request WHERE source_id = ?", f"{UUID_A}#1")[0]
    assert declined["merged_at"] is None and declined["closed_at"] is not None
    assert "pr_activity" in {r["kind"] for r in rows(conn, "SELECT kind FROM raw_payload")}


def test_running_out_of_budget_is_progress_not_failure_and_the_next_run_continues(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    # validate 2 + repository 1 + commits 1 + pull request list 1 = 5; each detail is 4 requests
    first = run_sync(conn, [connector_for(path, fake, budget=9)])
    assert first[0].status == "ok"
    assert repo_selection.detail_progress(conn, UUID_A) == (1, 3)
    newest = rows(conn, "SELECT record_id FROM property WHERE name = 'detail_updated_on'")
    assert [r["record_id"] for r in newest] == [f"{UUID_A}#3"]
    second = run_sync(conn, [connector_for(path, fake, budget=13)])
    assert second[0].status == "ok"
    assert repo_selection.detail_progress(conn, UUID_A) == (3, 3)


def test_a_second_sync_skips_unchanged_pull_requests_and_keeps_exact_times(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    exact = rows(conn, "SELECT merged_at FROM change_request WHERE source_id = ?", f"{UUID_A}#3")[0]["merged_at"]
    before = fake.count("/activity")
    run_sync(conn, [connector_for(path, fake)])
    assert fake.count("/activity") == before  # nothing was detailed again
    again = rows(conn, "SELECT merged_at FROM change_request WHERE source_id = ?", f"{UUID_A}#3")[0]["merged_at"]
    assert again == exact


def test_a_pull_request_updated_after_detail_is_detailed_again(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    later = recent(0.5)
    repo = fake.repos["movedocs_v1.0"]
    repo["prs"][1]["updated_on"] = later  # PR 2 changes
    repo["activity"][2] = [comment(21, recent(2)), comment(22, later)]
    before = fake.count("/pullrequests/2/activity")
    run_sync(conn, [connector_for(path, fake)])
    assert fake.count("/pullrequests/2/activity") == before + 1
    assert fake.count("/pullrequests/3/activity") == 1
    comments = rows(conn, "SELECT source_id FROM change_event WHERE change_request_id = ? AND type = 'comment'", f"{UUID_A}#2")
    assert len(comments) == 2


def test_a_pull_request_that_disappears_in_detail_does_not_fail_the_repository(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    fake.errors["/pullrequests/2/activity"] = 404
    conn, path = build(tmp_path, fake)
    results = run_sync(conn, [connector_for(path, fake)])
    assert results[0].status == "ok"
    marker = rows(conn, "SELECT value FROM property WHERE record_id = ? AND name = 'detail_updated_on'", f"{UUID_A}#2")
    assert len(marker) == 1
    assert repo_selection.detail_progress(conn, UUID_A) == (3, 3)


def _owners(conn):
    return {r["sha"]: r["change_request_id"] for r in rows(conn, "SELECT sha, change_request_id FROM vcs_commit")}


def test_a_large_unmerged_pr_does_not_take_commits_from_a_merged_feature_pr(tmp_path):
    fake = FakeBitbucket()
    # PR 5 (declined, built from the wrong branch) holds PR 4's commits plus others; it is detailed after PR 4.
    fake.add_repo(
        "movedocs_v1.0", UUID_A,
        prs=[pr(4, "MERGED", recent(1)), pr(5, "DECLINED", recent(2))],
        activity={4: [update("MERGED", recent(1))], 5: [update("DECLINED", recent(2))]},
        pr_commits={4: [{"hash": "h1"}, {"hash": "h2"}], 5: [{"hash": h} for h in ("h1", "h2", "h3", "h4")]},
        diffstat={4: [{"status": "modified"}], 5: [{"status": "modified"}]},
    )
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    owners = _owners(conn)
    assert owners["h1"] == owners["h2"] == f"{UUID_A}#4"
    assert owners["h3"] == owners["h4"] == f"{UUID_A}#5"


def test_a_merged_release_pr_does_not_take_commits_from_a_smaller_merged_pr(tmp_path):
    fake = FakeBitbucket()
    fake.add_repo(
        "movedocs_v1.0", UUID_A,
        prs=[pr(4, "MERGED", recent(1)), pr(6, "MERGED", recent(2), branch="release/v1")],
        activity={4: [update("MERGED", recent(1))], 6: [update("MERGED", recent(2))]},
        pr_commits={4: [{"hash": "h1"}], 6: [{"hash": "h1"}, {"hash": "h9"}]},
        diffstat={4: [{"status": "modified"}], 6: [{"status": "modified"}]},
    )
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    assert _owners(conn) == {"h1": f"{UUID_A}#4", "h9": f"{UUID_A}#6"}


def test_a_merged_pr_reclaims_commits_held_by_an_unmerged_one(tmp_path):
    fake = FakeBitbucket()
    # The declined PR is detailed first and is smaller, but a merged PR still wins its commit.
    fake.add_repo(
        "movedocs_v1.0", UUID_A,
        prs=[pr(7, "DECLINED", recent(1)), pr(8, "MERGED", recent(2))],
        activity={7: [update("DECLINED", recent(1))], 8: [update("MERGED", recent(2))]},
        pr_commits={7: [{"hash": "h1"}], 8: [{"hash": "h1"}, {"hash": "h2"}]},
        diffstat={7: [{"status": "modified"}], 8: [{"status": "modified"}]},
    )
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    assert _owners(conn) == {"h1": f"{UUID_A}#8", "h2": f"{UUID_A}#8"}


def test_migration_requeues_merged_prs_that_lost_their_commits(tmp_path):
    from pathlib import Path
    import delivery_analysis.store as store

    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    sid3 = f"{UUID_A}#3"
    conn.execute("UPDATE vcs_commit SET change_request_id = ? WHERE change_request_id = ?", (f"{UUID_A}#2", sid3))
    conn.commit()
    sql = (Path(store.__file__).parent / "migrations" / "0013_relink_pr_commits.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    detailed = {r["record_id"] for r in rows(conn, "SELECT record_id FROM property WHERE name = 'detail_updated_on'")}
    assert sid3 not in detailed  # merged, reports commits, has none linked: fetched again
    assert f"{UUID_A}#2" in detailed  # still has its commits
    run_sync(conn, [connector_for(path, fake)])
    assert {r["sha"] for r in rows(conn, "SELECT sha FROM vcs_commit WHERE change_request_id = ?", sid3)} == {"h1", "h2"}
