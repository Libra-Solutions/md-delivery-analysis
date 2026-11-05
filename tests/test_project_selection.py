import pytest

from tests.schema import LATEST_SCHEMA
from delivery_analysis.model.records import Record
from delivery_analysis.store import db
from delivery_analysis.store import project_selection as ps
from delivery_analysis.store.upsert import upsert_record

NOW = "2026-10-15T00:00:00Z"


def test_migration_four_creates_the_tables(conn):
    names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"project_selection", "status_mapping"} <= names
    assert db.current_version(conn) == LATEST_SCHEMA


def test_add_is_an_upsert_and_keeps_a_chosen_points_field(conn):
    ps.add_project(conn, "jira", "MD", "10001", "Move Docs", "customfield_10004", NOW)
    ps.add_project(conn, "jira", "MD", "10001", "Move Docs 2", None, NOW)
    row = ps.get_project(conn, "jira", "MD")
    assert (row["name"], row["story_points_field"], row["excluded_types"]) == (
        "Move Docs 2", "customfield_10004", "Epic,Initiative"
    )
    ps.add_project(conn, "jira", "MD", "10001", "Move Docs 2", "customfield_11168", NOW)
    assert ps.get_project(conn, "jira", "MD")["story_points_field"] == "customfield_11168"
    assert ps.get_project(conn, "jira", "ZZ") is None


def test_list_is_sorted_and_filtered_by_source(conn):
    ps.add_project(conn, "jira", "ZZ", "2", "Zed", None, NOW)
    ps.add_project(conn, "jira", "AA", "1", "Aye", None, NOW)
    ps.add_project(conn, "other", "QQ", "3", "Queue", None, NOW)
    assert [r["project_key"] for r in ps.list_projects(conn, "jira")] == ["AA", "ZZ"]
    assert len(ps.list_projects(conn)) == 3


def test_remove_deletes_the_selection_but_keeps_the_status_map(conn):
    ps.add_project(conn, "jira", "MD", "1", "Move Docs", None, NOW)
    ps.set_status(conn, "jira", "MD", "COMPLETED", "done")
    assert ps.remove_project(conn, "jira", "MD") == 1
    assert ps.remove_project(conn, "jira", "MD") == 0
    assert ps.status_map(conn, "jira", "MD") == {"COMPLETED": "done"}


def test_seed_never_overwrites_a_manual_choice_but_set_does(conn):
    ps.set_status(conn, "jira", "MD", "Dev Done", "in_review")
    ps.seed_statuses(conn, "jira", "MD", {"Dev Done": "in_progress", "To Do": "todo"})
    assert ps.status_map(conn, "jira", "MD") == {"Dev Done": "in_review", "To Do": "todo"}
    ps.set_status(conn, "jira", "MD", "Dev Done", "in_progress")
    assert ps.status_map(conn, "jira", "MD")["Dev Done"] == "in_progress"


def test_set_status_rejects_unknown_categories_and_blank_names(conn):
    with pytest.raises(ValueError, match="todo, in_progress, in_review, done, dropped"):
        ps.set_status(conn, "jira", "MD", "COMPLETED", "finished")
    with pytest.raises(ValueError, match="status name"):
        ps.set_status(conn, "jira", "MD", "  ", "done")


def test_issue_count_and_unmapped_seen_use_synced_issues(conn):
    for number, status in ((1, "To Do"), (2, "Weird"), (3, "Weird"), (4, "COMPLETED")):
        upsert_record(
            conn,
            Record("work_item", {"source": "jira", "source_id": str(number), "project": "MD", "status": status}),
            NOW,
        )
    upsert_record(conn, Record("work_item", {"source": "jira", "source_id": "9", "project": "OTHER", "status": "X"}), NOW)
    ps.seed_statuses(conn, "jira", "MD", {"To Do": "todo", "COMPLETED": "done"})
    assert ps.issue_count(conn, "jira", "MD") == 4
    assert ps.unmapped_seen(conn, "jira", "MD") == ["Weird"]
