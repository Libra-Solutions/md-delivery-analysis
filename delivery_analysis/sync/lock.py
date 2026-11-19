"""One sync at a time per database, across processes.

The app's background refresh, `delivery-analysis sync` and `backfill` all write the same SQLite file. Run together
they fight over its write lock until one fails with "database is locked". Each takes this lock first: a file next to
the database, locked by the operating system, so it is released when the holder exits, even if it crashes.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

if os.name == "nt":
    import msvcrt
else:
    import fcntl

POLL_SECONDS = 10.0
# How long a command-line sync or backfill waits for the lock before giving up.
CLI_WAIT_SECONDS = 2 * 3600.0


class SyncBusy(RuntimeError):
    """Another sync or backfill holds the lock."""


def lock_path(db: Union[str, Path, sqlite3.Connection]) -> Optional[Path]:
    """The lock file for a database path or open connection; None for an in-memory database."""
    if isinstance(db, sqlite3.Connection):
        row = db.execute("PRAGMA database_list").fetchone()
        db = row[2] if row is not None else ""
    text = str(db)
    if not text or text == ":memory:":
        return None
    return Path(text + ".sync-lock")


def _try_lock(handle) -> bool:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def sync_lock(
    db: Union[str, Path, sqlite3.Connection],
    wait_seconds: float = 0.0,
    on_wait: Optional[Callable[[], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[None]:
    """Hold the database's sync lock for the block.

    Raises SyncBusy when another holder keeps it longer than `wait_seconds` (0 means do not wait). `on_wait` is
    called once, the first time this has to wait."""
    path = lock_path(db)
    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        deadline = clock() + max(0.0, wait_seconds)
        told = False
        while not _try_lock(handle):
            remaining = deadline - clock()
            if remaining <= 0:
                raise SyncBusy("Another sync or backfill is running on this database.")
            if not told and on_wait is not None:
                on_wait()
                told = True
            sleep(min(POLL_SECONDS, remaining))
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()
