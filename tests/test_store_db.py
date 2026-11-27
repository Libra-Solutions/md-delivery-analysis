import sqlite3

import pytest

from tests.schema import LATEST_SCHEMA
from delivery_analysis.store import db

EXPECTED_TABLES = {
    "person", "identity", "repository", "change_request", "change_event", "vcs_commit",
    "work_item", "work_item_transition", "document", "document_version", "link",
    "property", "token_usage", "token_attribution", "raw_payload", "sync_state",
    "team", "team_repo", "team_member", "possible_duplicate",
    "repo_selection", "project_selection", "status_mapping",
    "schema_version",
}


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row["name"] for row in rows}


def test_connect_creates_a_missing_folder_and_uses_wal(tmp_path):
    target = tmp_path / "does" / "not" / "exist" / "delivery.sqlite"
    conn = db.connect(target)
    assert target.parent.is_dir()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_migrate_creates_every_table_and_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite")
    assert db.current_version(conn) == 0
    assert db.migrate(conn) == LATEST_SCHEMA
    assert EXPECTED_TABLES <= table_names(conn)
    assert db.migrate(conn) == LATEST_SCHEMA
    conn.close()


def test_upgrade_from_the_previous_version_keeps_data(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_a.sql").write_text(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);", encoding="utf-8"
    )
    conn = db.connect(tmp_path / "d.sqlite")
    assert db.migrate(conn, migrations) == 1
    conn.execute("INSERT INTO t (id, name) VALUES (1, 'kept')")
    (migrations / "0002_b.sql").write_text("ALTER TABLE t ADD COLUMN extra TEXT;", encoding="utf-8")
    assert db.migrate(conn, migrations) == 2
    row = conn.execute("SELECT name, extra FROM t").fetchone()
    assert (row["name"], row["extra"]) == ("kept", None)
    conn.close()


def test_a_failing_migration_rolls_back_completely(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_bad.sql").write_text(
        "CREATE TABLE half (id INTEGER);\nTHIS IS NOT SQL;", encoding="utf-8"
    )
    conn = db.connect(tmp_path / "d.sqlite")
    with pytest.raises(sqlite3.Error):
        db.migrate(conn, migrations)
    assert db.current_version(conn) == 0
    assert "half" not in table_names(conn)
    assert not conn.in_transaction
    conn.close()


def test_read_indexes_exist_after_migrate(tmp_path):
    conn = db.connect(tmp_path / "i.sqlite")
    db.migrate(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_change_event_change_request", "idx_link_from", "idx_link_to",
            "idx_raw_payload_source_fetched"} <= names
    plan = " ".join(str(tuple(r)) for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT 1 FROM change_event WHERE change_request_id = ? AND type = 'approved'", ("x",)))
    assert "idx_change_event_change_request" in plan
    conn.close()


def test_remembered_reads_once_per_connection_until_it_writes(tmp_path):
    conn = db.connect(tmp_path / "m.sqlite")
    db.migrate(conn)
    calls = []
    build = lambda: calls.append(1) or len(calls)  # noqa: E731
    assert db.remembered(conn, "k", build) == 1
    assert db.remembered(conn, "k", build) == 1
    conn.execute("INSERT INTO person (person_id, display_name, excluded, manual) VALUES ('p', 'P', 0, 1)")
    assert db.remembered(conn, "k", build) == 2
    other = db.connect(tmp_path / "m.sqlite")
    assert db.remembered(other, "k", build) == 3  # a new connection (request) reads again
    plain = sqlite3.connect(":memory:")
    assert db.remembered(plain, "k", build) == 4 and db.remembered(plain, "k", build) == 5
    conn.close(); other.close(); plain.close()
