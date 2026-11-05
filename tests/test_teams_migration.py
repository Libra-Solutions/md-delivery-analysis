import shutil
import sqlite3

from delivery_analysis.store import db
from tests.schema import LATEST_SCHEMA


def columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def tables(conn):
    return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_database_gets_the_team_schema(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite")
    assert db.migrate(conn) == LATEST_SCHEMA
    assert {"team", "team_repo", "team_member", "possible_duplicate"} <= tables(conn)
    assert {"author_name", "author_email"} <= columns(conn, "vcs_commit")
    assert {"excluded", "manual"} <= columns(conn, "person")
    assert "manual" in columns(conn, "identity")
    conn.close()


def test_upgrading_from_version_1_keeps_existing_rows(tmp_path):
    only_v1 = tmp_path / "v1"
    only_v1.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_initial.sql", only_v1 / "0001_initial.sql")
    conn = db.connect(tmp_path / "d.sqlite")
    assert db.migrate(conn, only_v1) == 1
    conn.execute("INSERT INTO person (person_id, display_name) VALUES ('p1', 'Ann Example')")
    conn.execute(
        "INSERT INTO identity (source, account_id, person_id) VALUES ('email', 'ann@corp.example', 'p1')"
    )
    conn.execute(
        "INSERT INTO vcs_commit (source, source_id, repository_id, fetched_at) "
        "VALUES ('bitbucket', 'c1', 'r1', '2026-10-15T00:00:00Z')"
    )
    assert db.migrate(conn) == LATEST_SCHEMA
    person = conn.execute("SELECT display_name, excluded, manual FROM person").fetchone()
    assert (person["display_name"], person["excluded"], person["manual"]) == ("Ann Example", 0, 0)
    assert conn.execute("SELECT manual FROM identity").fetchone()["manual"] == 0
    commit = conn.execute("SELECT author_name, author_email FROM vcs_commit").fetchone()
    assert (commit["author_name"], commit["author_email"]) == (None, None)
    conn.close()


def test_team_member_status_is_restricted(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO person (person_id, display_name) VALUES ('p1', 'Ann Example')")
    conn.execute("INSERT INTO team (team_id, name, created_at) VALUES ('t1', 'Core', '2026-10-15T00:00:00Z')")
    try:
        conn.execute("INSERT INTO team_member (team_id, person_id, status) VALUES ('t1', 'p1', 'retired')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("an unknown status must be rejected")
    conn.close()
