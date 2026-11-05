import argparse
from types import SimpleNamespace

import pytest

from delivery_analysis.cli import cohort as cohort_cli
from delivery_analysis.store import cohort


@pytest.fixture
def people(conn):
    rows = [("p-bo", "Bo Example"), ("p-ann", "Ann Example"), ("p-ann2", "ann example"), ("p-cy", "Cy Example")]
    for pid, name in rows:
        conn.execute("INSERT INTO person (person_id, display_name) VALUES (?, ?)", (pid, name))
    conn.commit()


def test_bad_level(conn, people):
    with pytest.raises(ValueError):
        cohort.set_member(conn, "p-bo", "Junior", "2026-09-19")


def test_bad_date(conn, people):
    with pytest.raises(ValueError):
        cohort.set_member(conn, "p-bo", "Mid", "2026-13-01")


def test_unknown_person(conn, people):
    with pytest.raises(LookupError):
        cohort.set_member(conn, "p-none", "Mid", "2026-09-19")


def test_set_and_list(conn, people):
    cohort.set_member(conn, "p-cy", "Senior", "2026-08-01")
    cohort.set_member(conn, "p-bo", "Mid", "2026-09-19")
    assert cohort.list_members(conn) == [
        {"person_id": "p-bo", "name": "Bo Example", "level": "Mid", "day0": "2026-09-19"},
        {"person_id": "p-cy", "name": "Cy Example", "level": "Senior", "day0": "2026-08-01"},
    ]


def test_set_updates(conn, people):
    cohort.set_member(conn, "p-bo", "Mid", "2026-09-19")
    cohort.set_member(conn, "p-bo", "Senior", "2026-10-01")
    assert cohort.list_members(conn) == [
        {"person_id": "p-bo", "name": "Bo Example", "level": "Senior", "day0": "2026-10-01"}
    ]


def test_remove(conn, people):
    cohort.set_member(conn, "p-bo", "Mid", "2026-09-19")
    assert cohort.remove_member(conn, "p-bo") is True
    assert cohort.remove_member(conn, "p-none") is False


def _run(tmp_path, *argv):
    parser = argparse.ArgumentParser()
    cohort_cli.register(parser.add_subparsers(dest="command"))
    settings = SimpleNamespace(db_path=tmp_path / "teams.sqlite")
    return cohort_cli.run(parser.parse_args(["cohort", *argv]), settings)


def test_cli_set_by_name(conn, people, tmp_path):
    assert _run(tmp_path, "set", "Bo EXAMPLE", "--level", "Mid", "--day0", "2026-09-19") == 0
    assert cohort.list_members(conn)[0]["person_id"] == "p-bo"
    # two people share this name ignoring case
    assert _run(tmp_path, "set", "Ann Example", "--level", "Mid", "--day0", "2026-09-19") == 2
    assert _run(tmp_path, "set", "Nobody", "--level", "Mid", "--day0", "2026-09-19") == 2
    assert _run(tmp_path, "set", "p-bo", "--level", "Junior", "--day0", "2026-09-19") == 2


def test_cli_list_and_remove(conn, people, tmp_path, capsys):
    cohort.set_member(conn, "p-bo", "Mid", "2026-09-19")
    assert _run(tmp_path, "list") == 0
    assert "Bo Example  Mid  Day 0 2026-09-19" in capsys.readouterr().out
    assert _run(tmp_path, "remove", "p-bo") == 0
    assert cohort.list_members(conn) == []
