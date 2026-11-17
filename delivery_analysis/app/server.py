from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from delivery_analysis.app.api import build_router
from delivery_analysis.app.context import AppContext, _utc_now
from delivery_analysis.app.refresh import RefreshWorker, sync_runner
from delivery_analysis.settings import Settings, redact, secret_values
from delivery_analysis.store.db import connect, current_version, migrate
from delivery_analysis.store.sync_state import list_sync_states
from delivery_analysis.store.upsert import unmapped_identities

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
PAGES: Dict[str, str] = {
    "/": "dashboard.html",
    "/rankings": "rankings.html",
    "/qa": "qa.html",
    "/people": "people.html",
    "/person": "person.html",
    "/selection": "selection.html",
    "/teams": "teams.html",
    "/sources": "sources.html",
    "/settings": "settings.html",
    "/ask": "ask.html",
}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _host_name(value: str) -> str:
    value = value.strip()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def create_app(
    db_path: Union[str, Path],
    *,
    settings: Optional[Settings] = None,
    environ: Optional[Mapping[str, str]] = None,
    transport: Optional[httpx.BaseTransport] = None,
    worker: Optional[RefreshWorker] = None,
    clock: Optional[Callable[[], datetime]] = None,
    allowed_hosts: Sequence[str] = LOCAL_HOSTS,
    port: Optional[int] = None,
    public_hosts: Sequence[str] = (),
) -> FastAPI:
    path = Path(db_path)
    settings = settings or Settings(db_path=path)
    env = dict(environ or {})
    worker = worker or RefreshWorker(
        sync_runner(path, settings, env, transport), redact=lambda text: redact(text, secret_values(env))
    )
    ctx = AppContext(path, settings, env, worker, transport, clock or _utc_now)
    app = FastAPI(title="Delivery analytics")
    public = {h.lower() for h in public_hosts}
    allowed = set(allowed_hosts) | public

    def _origin_ok(origin: str) -> bool:
        parsed = urlparse(origin)
        if (parsed.hostname or "") in public:
            # Public names are reached through a TLS proxy: the browser origin is https on the default port.
            try:
                return parsed.scheme == "https" and parsed.port in (None, 443)
            except ValueError:
                return False
        if (parsed.hostname or "") not in allowed:
            return False
        if port is None:
            return True
        if parsed.scheme != "http":  # the app only serves plain http
            return False
        try:
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return False
        return origin_port == port

    setup = connect(path)
    try:
        migrate(setup)
    finally:
        setup.close()

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Any:
        if _host_name(request.headers.get("host", "")).lower() not in allowed:
            return JSONResponse({"detail": "This app only answers on localhost."}, status_code=403)
        if request.method in WRITE_METHODS:
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site", "").lower()
            if site in ("cross-site", "same-site") or (origin and not _origin_ok(origin)):
                return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"  # pages and scripts change with the app; always revalidate
        return response

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        conn = connect(path)
        try:
            return {
                "schema_version": current_version(conn),
                "sources": list_sync_states(conn),
                "unmapped_identities": len(unmapped_identities(conn)),
            }
        finally:
            conn.close()

    app.include_router(build_router(ctx))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def page(filename: str) -> Callable[[], FileResponse]:
        def serve() -> FileResponse:
            return FileResponse(STATIC_DIR / filename)
        return serve

    for route, filename in PAGES.items():
        app.add_api_route(route, page(filename), methods=["GET"], include_in_schema=False)
    app.state.context = ctx
    return app
