from __future__ import annotations

import hashlib

from delivery_analysis.app.context import AppContext
from delivery_analysis.store.db import connect
from delivery_analysis.store.sync_state import list_sync_states


def data_version(ctx: AppContext) -> str:
    """A short token that changes whenever the data the API serves may have changed.

    While a background refresh runs, the token from before it started is kept (unless a write
    happens), so caches keyed by it stay valid mid-sync and turn over once, when the refresh ends.
    """
    held = ctx.last_version
    if held is not None and held[0] == ctx.write_count and ctx.worker.state().get("running"):
        return held[1]
    conn = connect(ctx.db_path)
    try:
        states = list_sync_states(conn)
    finally:
        conn.close()
    parts = [f"{s['connector']}/{s['scope']}={s['last_run']}:{s['status']}" for s in states]
    finished = ctx.worker.state().get("finished_at")
    parts = sorted(parts)
    parts.append(f"refresh={finished}")
    parts.append(f"writes={ctx.started_at}:{ctx.write_count}")
    version = hashlib.sha1("\n".join(parts).encode()).hexdigest()[:12]
    ctx.last_version = (ctx.write_count, version)
    return version
