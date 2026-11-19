from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

import httpx

from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.settings import Settings, redact, secret_values
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.store.sync_state import clear_state, list_sync_states
from delivery_analysis.sync.lock import SyncBusy, sync_lock
from delivery_analysis.sync.runner import utc_now_iso
from delivery_analysis.sync.service import sync_and_reconcile

RunFn = Callable[[Optional[str], bool], str]

BUSY_SUMMARY = "Skipped: a backfill or another sync is running. Refresh again once it finishes."


class RefreshWorker:
    """Runs one background sync at a time and remembers how the last one went."""

    def __init__(self, run: RunFn, redact: Optional[Callable[[str], str]] = None) -> None:
        self._run = run
        self._redact = redact or (lambda text: text)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._state: Dict[str, Any] = {
            "running": False, "source": None, "full": False,
            "started_at": None, "finished_at": None, "error": None, "summary": None,
        }

    def start(self, source: Optional[str] = None, full: bool = False) -> bool:
        with self._lock:
            if self._state["running"]:
                return False
            self._state.update({
                "running": True, "source": source, "full": full, "started_at": utc_now_iso(),
                "finished_at": None, "error": None, "summary": None,
            })
            self._thread = threading.Thread(target=self._work, args=(source, full), daemon=True)
            self._thread.start()
            return True

    def _work(self, source: Optional[str], full: bool) -> None:
        error: Optional[str] = None
        summary: Optional[str] = None
        try:
            result = self._run(source, full)
            summary = None if result is None else self._redact(result)
        except Exception as exc:
            error = self._redact(str(exc) or exc.__class__.__name__)
        with self._lock:
            self._state.update({"running": False, "finished_at": utc_now_iso(), "error": error, "summary": summary})

    def state(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def wait(self, timeout: float = 10.0) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)


def sync_runner(
    db_path: Path,
    settings: Settings,
    environ: Mapping[str, str],
    transport: Optional[httpx.BaseTransport] = None,
) -> RunFn:
    """The real refresh: the same sync and team update as `delivery-analysis sync`."""

    def _locked(connectors, source: Optional[str], full: bool):
        conn = connect(db_path)
        try:
            migrate(conn)
            if full:
                names = {connector.name for connector in connectors}
                for state in list_sync_states(conn):
                    if state["connector"] in names:
                        clear_state(conn, state["connector"], state["scope"])
            return sync_and_reconcile(
                conn, connectors, settings, environ, only=source,
                fetch_code=bool((environ.get("BITBUCKET") or "").strip()),
            )
        finally:
            conn.close()

    def run(source: Optional[str], full: bool) -> str:
        secrets = secret_values(environ)
        connectors = build_connectors(settings, environ, transport)
        if source is not None:
            connectors = [connector for connector in connectors if connector.name == source]
        if not connectors:
            return "No connectors are configured."
        try:
            with sync_lock(db_path):
                results, lines, failed_teams = _locked(connectors, source, full)
        except SyncBusy:
            return BUSY_SUMMARY
        failed = sum(1 for result in results if result.status == "failed")
        text = f"{len(results) - failed} ok, {failed} failed"
        if failed_teams:
            text += f", {failed_teams} team update failed"
        for line in lines:
            if "build failed" in line:
                text += "; " + line
        return redact(text, secrets)

    return run
