from delivery_analysis.metrics import coverage


def test_coverage_dates(conn):
    conn.execute(
        "INSERT INTO work_item (source, source_id, status, status_category, resolved_at, delivered_at, fetched_at) "
        "VALUES ('jira', 'MD-1', 'Dev Done', 'done', '2025-12-01T00:00:00Z', '2025-11-03T10:00:00Z', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO work_item (source, source_id, status, status_category, resolved_at, delivered_at, fetched_at) "
        "VALUES ('jira', 'MD-2', 'Dev Done', 'done', '2025-12-05T00:00:00Z', '2025-12-05T00:00:00Z', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO change_request (source, source_id, repository_id, created_at, fetched_at) "
        "VALUES ('bitbucket', 'pr-2', 'r1', '2026-07-01T09:00:00Z', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO change_request (source, source_id, repository_id, created_at, fetched_at) "
        "VALUES ('bitbucket', 'pr-1', 'r1', '2026-06-12T09:00:00Z', '2026-10-15T00:00:00Z')"
    )
    # Commit without a commit_file row is ignored.
    conn.execute(
        "INSERT INTO vcs_commit (source, source_id, repository_id, sha, committed_at, fetched_at) "
        "VALUES ('bitbucket', 'c-0', 'r1', 'sha0', '2026-01-02T08:00:00Z', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO vcs_commit (source, source_id, repository_id, sha, committed_at, fetched_at) "
        "VALUES ('bitbucket', 'c-1', 'r1', 'sha1', '2026-05-14T08:00:00Z', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO commit_file (repository_id, sha, path, fetched_at) VALUES ('r1', 'sha1', 'a.py', '2026-10-15T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO person (person_id, display_name) VALUES ('p1', 'Ann Example')"
    )
    conn.execute(
        "INSERT INTO token_usage (person_id, day, model, purpose, cost_usd, total_tokens, source, "
        "purpose_method, purpose_confidence) VALUES ('p1', '2026-07-23', 'm', 'ask', 1.0, 10, 'claude', 'x', 'high')"
    )
    conn.execute(
        "INSERT INTO token_usage (person_id, day, model, purpose, cost_usd, total_tokens, source, "
        "purpose_method, purpose_confidence) VALUES ('p1', '2026-08-01', 'm', 'ask', 2.0, 20, 'claude', 'x', 'high')"
    )
    conn.execute(
        "INSERT INTO sync_state (connector, scope, last_run) VALUES ('jira', 'a', '2026-10-29T16:28:05Z')"
    )
    conn.execute(
        "INSERT INTO sync_state (connector, scope, last_run) VALUES ('bitbucket', 'b', '2026-10-30T16:28:05Z')"
    )

    assert coverage.data_coverage(conn) == {
        "jira_delivered": "2025-11-03",
        "pull_requests": "2026-06-12",
        "file_data": "2026-05-14",
        "claude": "2026-07-23",
        "last_sync": "2026-10-30T16:28:05Z",
    }


def test_coverage_empty(conn):
    assert coverage.data_coverage(conn) == {
        "jira_delivered": None,
        "pull_requests": None,
        "file_data": None,
        "claude": None,
        "last_sync": None,
    }
