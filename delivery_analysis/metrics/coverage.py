"""Data coverage (T4): the earliest date each data source covers, and the last sync time."""

from __future__ import annotations

import sqlite3

from delivery_analysis.metrics.delivered import DELIVERED_AT_SQL


def _date(value):
    return value[:10] if value else None


def data_coverage(conn: sqlite3.Connection) -> dict:
    """Earliest date (YYYY-MM-DD) of each source, and the latest sync run (full timestamp); None when empty."""
    jira = conn.execute(f"SELECT MIN({DELIVERED_AT_SQL}) FROM work_item w").fetchone()[0]
    prs = conn.execute("SELECT MIN(created_at) FROM change_request").fetchone()[0]
    files = conn.execute(
        "SELECT MIN(c.committed_at) FROM vcs_commit c WHERE EXISTS ("
        "SELECT 1 FROM commit_file f WHERE f.repository_id = c.repository_id AND f.sha = c.sha)"
    ).fetchone()[0]
    claude = conn.execute("SELECT MIN(day) FROM token_usage").fetchone()[0]
    last_sync = conn.execute("SELECT MAX(last_run) FROM sync_state").fetchone()[0]
    return {
        "jira_delivered": _date(jira),
        "pull_requests": _date(prs),
        "file_data": _date(files),
        "claude": _date(claude),
        "last_sync": last_sync or None,
    }
