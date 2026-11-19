import sqlite3
from contextlib import ExitStack
from pathlib import Path

import pytest

from delivery_analysis.app import refresh
from delivery_analysis.settings import Settings
from delivery_analysis.sync import backfill as bf
from delivery_analysis.sync.lock import SyncBusy, lock_path, sync_lock


class _Fake:
    name = "bitbucket"


def test_lock_file_sits_next_to_the_database(tmp_path, conn):
    assert lock_path(tmp_path / "d.sqlite") == Path(str(tmp_path / "d.sqlite") + ".sync-lock")
    assert lock_path(conn) == Path(str(tmp_path / "teams.sqlite") + ".sync-lock")
    assert lock_path(":memory:") is None
    assert lock_path(sqlite3.connect(":memory:")) is None


def test_second_holder_is_turned_away_without_waiting(tmp_path):
    db = tmp_path / "d.sqlite"
    with sync_lock(db):
        with pytest.raises(SyncBusy):
            with sync_lock(db):
                pass


def test_lock_is_free_again_after_the_block(tmp_path):
    db = tmp_path / "d.sqlite"
    with sync_lock(db):
        pass
    with sync_lock(db):
        pass


def test_lock_is_released_when_the_block_raises(tmp_path):
    db = tmp_path / "d.sqlite"
    with pytest.raises(ValueError):
        with sync_lock(db):
            raise ValueError("boom")
    with sync_lock(db):
        pass


def test_waiter_gets_the_lock_once_the_holder_finishes(tmp_path):
    db = tmp_path / "d.sqlite"
    holder = ExitStack()
    holder.enter_context(sync_lock(db))
    told, slept = [], []

    def sleep(seconds):
        slept.append(seconds)
        holder.close()  # the other sync finishes while this one waits

    with sync_lock(db, wait_seconds=60, on_wait=lambda: told.append(1), sleep=sleep, clock=lambda: 0.0):
        pass
    assert told == [1] and slept == [10.0]


def test_waiter_gives_up_at_its_deadline(tmp_path):
    db = tmp_path / "d.sqlite"
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    with sync_lock(db):
        with pytest.raises(SyncBusy):
            with sync_lock(db, wait_seconds=25, sleep=sleep, clock=lambda: now[0]):
                pass
    assert now[0] == 25.0


def test_in_memory_database_needs_no_lock():
    with sync_lock(":memory:"):
        with sync_lock(":memory:"):
            pass


def test_app_refresh_skips_while_a_backfill_runs(tmp_path, monkeypatch):
    db = tmp_path / "d.sqlite"
    synced = []
    monkeypatch.setattr(refresh, "build_connectors", lambda *a, **k: [_Fake()])
    monkeypatch.setattr(refresh, "sync_and_reconcile", lambda *a, **k: synced.append(1) or ([], [], 0))
    run = refresh.sync_runner(db, Settings(db_path=db), {})
    with sync_lock(db):
        assert run(None, False) == refresh.BUSY_SUMMARY
    assert synced == []
    assert run(None, False) == "0 ok, 0 failed"
    assert synced == [1]


def test_backfill_waits_for_a_running_sync_and_says_so(conn, monkeypatch):
    settings = Settings(db_path=Path("unused.sqlite"))
    monkeypatch.setattr(bf, "build_connectors", lambda *a, **k: [])
    monkeypatch.setattr(bf, "sync_and_reconcile", lambda *a, **k: ([], [], 0))
    lines = []
    with sync_lock(conn):
        with pytest.raises(SyncBusy):
            bf.backfill(conn, settings, {}, 450, log=lines.append, lock_wait=0.01)
    assert any("waiting for it to finish" in line for line in lines)
    assert bf.backfill(conn, settings, {}, 450, log=lines.append) == ([], [], 0)
