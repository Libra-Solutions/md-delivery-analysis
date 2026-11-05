from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from delivery_analysis.connectors.base import Connector
from delivery_analysis.model.records import Batch
from delivery_analysis.settings import redact
from delivery_analysis.store import fetched_range, sync_state
from delivery_analysis.store.upsert import write_batch

_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


@dataclass
class SourceResult:
    connector: str
    scope: str
    status: str  # "ok" or "failed"
    records: int
    error: Optional[str]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_ISO_Z)


def shift_cursor(cursor: Optional[str], days: int) -> Optional[str]:
    """Move a stored cursor back by `days`. Empty or unparseable cursors mean a full sync (None)."""
    if not cursor:
        return None
    try:
        parsed = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed - timedelta(days=days)).astimezone(timezone.utc).strftime(_ISO_Z)


def _commit_batch(
    conn: sqlite3.Connection, connector: str, scope: str, batch: Batch, fetched_at: str
) -> int:
    """Write one batch and move its cursor in a single transaction."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        written = write_batch(conn, batch, fetched_at)
        if batch.cursor is not None:
            sync_state.set_cursor(conn, connector, scope, batch.cursor)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return written


def _record_range(conn: sqlite3.Connection, connector: str, scope: str, since: Optional[str],
                  before: Optional[str]) -> None:
    """Remember that [since, new cursor] is fetched, when this run started from a known date and finished.

    A run cut short (no new cursor) or one that started from the connector's own window records nothing."""
    after = sync_state.get_cursor(conn, connector, scope)
    if not since or not after or after == before:
        return
    try:
        conn.execute("BEGIN IMMEDIATE")
        fetched_range.add(conn, connector, scope, since, after)
        conn.execute("COMMIT")
    except sqlite3.Error:  # never fail a sync over bookkeeping (for example an older database)
        if conn.in_transaction:
            conn.execute("ROLLBACK")


def _run_job(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    connector: Connector,
    scope: str,
    overlap_days: int,
    redact_values: Sequence[str],
    now: Callable[[], str],
    emit: Callable[[str], None],
) -> SourceResult:
    total = 0
    try:
        with lock:
            cursor = sync_state.get_cursor(conn, connector.name, scope)
        since = shift_cursor(cursor, overlap_days)
        for batch in connector.sync(scope, since):
            with lock:
                total += _commit_batch(conn, connector.name, scope, batch, now())
        with lock:
            _record_range(conn, connector.name, scope, since, cursor)
            sync_state.save_state(
                conn, connector.name, scope, status="ok", error=None, records=total, now=now()
            )
        emit(f"{connector.name}/{scope}: ok, {total} record(s)")
        return SourceResult(connector.name, scope, "ok", total, None)
    except Exception as exc:
        return _record_failure(conn, lock, connector.name, scope, total, exc, redact_values, now, emit)


def _record_failure(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    connector_name: str,
    scope: str,
    total: int,
    exc: Exception,
    redact_values: Sequence[str],
    now: Callable[[], str],
    emit: Callable[[str], None],
) -> SourceResult:
    """Redact, persist (best effort) and report a failure without ever raising."""
    message = redact(str(exc) or exc.__class__.__name__, redact_values)
    try:
        with lock:
            sync_state.save_state(
                conn, connector_name, scope, status="failed", error=message, records=total, now=now()
            )
    except Exception:
        pass
    emit(f"{connector_name}/{scope}: FAILED, {message}")
    return SourceResult(connector_name, scope, "failed", total, message)


def _safe_emit(log: Optional[Callable[[str], None]]) -> Callable[[str], None]:
    """Wrap the log callback so a failing sink can never abort or fail a sync."""

    def emit(message: str) -> None:
        if log is None:
            return
        try:
            log(message)
        except Exception:
            pass

    return emit


def _run_connector(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    connector: Connector,
    scopes: Sequence[str],
    overlap_days: int,
    redact_values: Sequence[str],
    now: Callable[[], str],
    emit: Callable[[str], None],
) -> List[SourceResult]:
    """One worker per connector: its scopes run one after another, in order."""
    return [
        _run_job(conn, lock, connector, scope, overlap_days, redact_values, now, emit)
        for scope in scopes
    ]


def run_sync(
    conn: sqlite3.Connection,
    connectors: Iterable[Connector],
    *,
    overlap_days: int = 7,
    only: Optional[str] = None,
    redact_values: Sequence[str] = (),
    now: Callable[[], str] = utc_now_iso,
    log: Optional[Callable[[str], None]] = None,
) -> List[SourceResult]:
    """Sync every connector in its own thread (scopes in order), one writer at a time."""
    emit = _safe_emit(log)
    lock = threading.Lock()
    failures: List[SourceResult] = []
    jobs: List[Tuple[Connector, List[str]]] = []
    for connector in connectors:
        if only is not None and connector.name != only:
            continue
        try:
            problems = connector.validate()
            if problems:
                raise RuntimeError("; ".join(problems))
            scopes = list(connector.scopes())
        except Exception as exc:
            failures.append(
                _record_failure(conn, lock, connector.name, "*", 0, exc, redact_values, now, emit)
            )
            continue
        try:
            with lock:
                sync_state.clear_state(conn, connector.name, "*")
        except Exception:
            pass
        if scopes:
            jobs.append((connector, scopes))
    if not jobs:
        return failures
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [
            pool.submit(
                _run_connector, conn, lock, connector, scopes, overlap_days, redact_values, now, emit
            )
            for connector, scopes in jobs
        ]
        results = list(failures)
        for future in futures:
            results.extend(future.result())
        return results
