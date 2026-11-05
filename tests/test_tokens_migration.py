import shutil

from delivery_analysis.store import db
from tests.schema import LATEST_SCHEMA


def columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def test_fresh_database_reaches_version_5_with_the_token_tables(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite")
    assert db.migrate(conn) == LATEST_SCHEMA
    assert columns(conn, "claude_usage_day") == [
        "source", "day", "actor_type", "actor", "model", "cost_usd", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_creation_tokens", "fetched_at",
    ]
    assert columns(conn, "claude_activity_day") == [
        "source", "day", "actor_type", "actor", "sessions", "lines_added", "lines_removed", "commits",
        "pull_requests", "edits_accepted", "edits_rejected", "tool_actions", "customer_types", "fetched_at",
    ]
    assert columns(conn, "token_usage") == [
        "person_id", "day", "model", "purpose", "cost_usd", "total_tokens", "source",
        "purpose_method", "purpose_confidence",
    ]
    assert columns(conn, "token_attribution") == [
        "person_id", "day", "work_item_source", "work_item_id", "cost_usd", "weight", "evidence",
        "method", "confidence", "reason", "inputs", "algo_version", "computed_at",
    ]
    assert columns(conn, "ticket_credit") == [
        "work_item_source", "work_item_id", "person_id", "share", "evidence", "method",
    ]
    conn.close()


def test_upgrade_from_version_4_replaces_the_empty_token_tables(tmp_path):
    older = tmp_path / "migrations"
    older.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("000[1-4]_*.sql")):
        shutil.copy(path, older / path.name)
    conn = db.connect(tmp_path / "d.sqlite")
    assert db.migrate(conn, older) == 4
    assert "method" in columns(conn, "token_attribution") and "reason" not in columns(conn, "token_attribution")
    assert db.migrate(conn) == LATEST_SCHEMA
    assert "reason" in columns(conn, "token_attribution")
    assert "purpose_method" in columns(conn, "token_usage")
    conn.close()


def test_actor_type_is_checked(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite")
    db.migrate(conn)
    try:
        conn.execute(
            "INSERT INTO claude_usage_day (source, day, actor_type, actor, model, cost_usd, fetched_at) "
            "VALUES ('s', '2026-03-01', 'nobody', 'x', 'm', 1.0, 'now')"
        )
        raised = False
    except Exception:
        raised = True
    assert raised
    conn.close()
