from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from delivery_analysis.app.context import AppContext
from delivery_analysis.cli.teams import parse_repo
from delivery_analysis.connectors.bitbucket.client import BitbucketClient, BitbucketError
from delivery_analysis.connectors.bitbucket.resolve import resolve_repository
from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.metrics.catalog import BY_NAME, METRICS
from delivery_analysis.metrics.export import person_csv, qa_csv
from delivery_analysis.metrics.matrix import people_matrix
from delivery_analysis.metrics.people import (
    People, map_identity, set_member_status, team_scope, unmapped_accounts,
)
from delivery_analysis.metrics.person import person_detail
from delivery_analysis.metrics.qa import qa_dashboard
from delivery_analysis.metrics.registry import describe, run_metric
from delivery_analysis.metrics.series import person_series
from delivery_analysis.metrics.tickets import ticket_costs
from delivery_analysis.metrics.window import ISO_Z, Window, make_window
from delivery_analysis.settings import CONFIG_VARS, CREDENTIAL_VARS, credential_status
from delivery_analysis.store import comparison
from delivery_analysis.store.db import connect
from delivery_analysis.store.repo_selection import (
    add_repo, detail_progress, list_selected, remove_repo, resolve as resolve_selected,
)
from delivery_analysis.store.sync_state import list_sync_states
from delivery_analysis.sync.runner import utc_now_iso
from delivery_analysis.teams.reconcile import create_team, reconcile_team

PLANNED_SOURCES = ("bitbucket", "jira", "claude_code_analytics", "confluence")


class TeamIn(BaseModel):
    name: str
    repos: List[str]
    window_days: int = Field(90, ge=1, le=9999)


class MemberIn(BaseModel):
    status: str


class ComparisonIn(BaseModel):
    person_ids: Optional[List[str]] = None  # None resets to the whole active team


class IdentityIn(BaseModel):
    source: str = "bitbucket"
    account: str
    person_id: Optional[str] = None
    new_name: Optional[str] = None
    team_id: Optional[str] = None


class RepoIn(BaseModel):
    repo: str


class RefreshIn(BaseModel):
    source: Optional[str] = None
    full: bool = False
    only_stale: bool = False


@contextmanager
def _db(ctx: AppContext) -> Iterator[sqlite3.Connection]:
    conn = connect(ctx.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _fail(ctx: AppContext, status: int, exc: Exception) -> HTTPException:
    return HTTPException(status_code=status, detail=ctx.clean(str(exc) or exc.__class__.__name__))


def _window(ctx: AppContext, conn: sqlite3.Connection, team: Optional[str], spec: Optional[str],
            start: Optional[str], end: Optional[str]) -> Window:
    default_days = ctx.settings.window_days
    if team:
        row = conn.execute("SELECT window_days FROM team WHERE team_id = ?", (team,)).fetchone()
        if row is not None:
            default_days = row["window_days"]
    return make_window(spec, ctx.settings.report_tz, ctx.today(), default_days=default_days, start=start, end=end)


def _team_repos(conn: sqlite3.Connection, team_id: str) -> List[Dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT t.repository_source AS source, t.repository_id, r.name FROM team_repo t "
        "LEFT JOIN repository r ON r.source = t.repository_source AND r.source_id = t.repository_id "
        "WHERE t.team_id = ? ORDER BY r.name, t.repository_id",
        (team_id,),
    )]


def _identities(conn: sqlite3.Connection, person_id: str) -> Dict[str, List[str]]:
    rows = conn.execute(
        "SELECT source, account_id FROM identity WHERE person_id = ? ORDER BY account_id", (person_id,)
    ).fetchall()
    return {
        "accounts": [row["account_id"] for row in rows if row["source"] != "email"],
        "emails": [row["account_id"] for row in rows if row["source"] == "email"],
    }


def _age_minutes(ctx: AppContext, last_run: Optional[str]) -> Optional[int]:
    if not last_run:
        return None
    then = datetime.strptime(last_run, ISO_Z).replace(tzinfo=timezone.utc)
    return int((ctx.clock() - then).total_seconds() // 60)


def _refresh_state(ctx: AppContext) -> Dict[str, Any]:
    state = ctx.worker.state()
    state["error"] = ctx.clean(state["error"])
    state["summary"] = ctx.clean(state["summary"])
    return state


def _anything_stale(ctx: AppContext, conn: sqlite3.Connection) -> bool:
    configured = {connector.name for connector in build_connectors(ctx.settings, ctx.environ, ctx.transport)}
    if not configured:
        return False
    states = [state for state in list_sync_states(conn) if state["connector"] in configured]
    if {state["connector"] for state in states} != configured:
        return True
    for state in states:
        age = _age_minutes(ctx, state["last_run"])
        if age is None or age >= ctx.settings.refresh_after_minutes:
            return True
    return False


def build_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/teams")
    def teams() -> Dict[str, Any]:
        with _db(ctx) as conn:
            out = []
            for row in conn.execute("SELECT team_id, name, window_days FROM team ORDER BY name").fetchall():
                counts = {"active": 0, "inactive": 0, "excluded": 0}
                for member in conn.execute(
                    "SELECT status, COUNT(*) AS n FROM team_member WHERE team_id = ? GROUP BY status",
                    (row["team_id"],),
                ):
                    counts[member["status"]] = member["n"]
                out.append({**dict(row), "repos": _team_repos(conn, row["team_id"]), "members": counts})
            return {"teams": out}

    @router.get("/teams/{team_id}")
    def team(team_id: str) -> Dict[str, Any]:
        with _db(ctx) as conn:
            row = conn.execute("SELECT team_id, name, window_days FROM team WHERE team_id = ?", (team_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"No team with id {team_id!r}.")
            members = []
            for member in conn.execute(
                "SELECT m.person_id, p.display_name AS name, m.status, m.last_commit, m.manual "
                "FROM team_member m JOIN person p ON p.person_id = m.person_id "
                "WHERE m.team_id = ? ORDER BY m.status, p.display_name",
                (team_id,),
            ).fetchall():
                members.append({**dict(member), "manual": bool(member["manual"]), **_identities(conn, member["person_id"])})
            duplicates = [dict(dup) for dup in conn.execute(
                "SELECT d.person_a, a.display_name AS name_a, d.person_b, b.display_name AS name_b, d.reason "
                "FROM possible_duplicate d JOIN person a ON a.person_id = d.person_a "
                "JOIN person b ON b.person_id = d.person_b WHERE d.status = 'open' "
                "AND (d.person_a IN (SELECT person_id FROM team_member WHERE team_id = ?) "
                "OR d.person_b IN (SELECT person_id FROM team_member WHERE team_id = ?))",
                (team_id, team_id),
            )]
            return {**dict(row), "repos": _team_repos(conn, team_id), "members": members,
                    "possible_duplicates": duplicates}

    @router.get("/identities/unmapped")
    def unmapped() -> Dict[str, Any]:
        with _db(ctx) as conn:
            return {"unmapped": unmapped_accounts(conn), "people": People(conn).all()}

    @router.get("/repos")
    def repos() -> Dict[str, Any]:
        with _db(ctx) as conn:
            states = {(s["connector"], s["scope"]): s for s in list_sync_states(conn)}
            out = []
            for row in list_selected(conn):
                state = states.get((row["source"], row["repository_id"])) or {}
                done, total = detail_progress(conn, row["repository_id"])
                out.append({**row, "status": state.get("status", "never"), "last_run": state.get("last_run"),
                            "error": ctx.clean(state.get("error")), "detail_done": done, "detail_total": total})
            return {"repos": out}

    @router.get("/sources")
    def sources() -> Dict[str, Any]:
        configured = [connector.name for connector in build_connectors(ctx.settings, ctx.environ, ctx.transport)]
        with _db(ctx) as conn:
            labels = {row["repository_id"]: f"{row['workspace']}/{row['slug']}" for row in list_selected(conn)}
            rows = [{
                "connector": state["connector"],
                "scope": state["scope"],
                "label": labels.get(state["scope"], state["scope"]),
                "status": state["status"],
                "last_run": state["last_run"],
                "error": ctx.clean(state["error"]),
                "failed": bool(state["stale"]),
                "age_minutes": _age_minutes(ctx, state["last_run"]),
            } for state in list_sync_states(conn)]
        return {
            "sources": rows,
            "configured": configured,
            "waiting": [name for name in PLANNED_SOURCES if name not in configured],
            "refresh_after_minutes": ctx.settings.refresh_after_minutes,
            "refresh": _refresh_state(ctx),
        }

    @router.get("/metrics")
    def metrics() -> Dict[str, Any]:
        with _db(ctx) as conn:
            return {"metrics": [describe(conn, metric) for metric in METRICS]}

    @router.get("/metrics/{name}")
    def metric(
        name: str,
        team: Optional[str] = None,
        window: Optional[str] = None,
        start: Optional[str] = Query(None, alias="from"),
        end: Optional[str] = Query(None, alias="to"),
        include_inactive: bool = False,
    ) -> Dict[str, Any]:
        definition = BY_NAME.get(name)
        if definition is None:
            raise HTTPException(status_code=404, detail=f"No metric named {name!r}.")
        with _db(ctx) as conn:
            try:
                scope = team_scope(conn, team, include_inactive)
                result = run_metric(
                    conn, definition, scope, _window(ctx, conn, team, window, start, end),
                    history_days=ctx.settings.window_days,
                )
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)
        if "error" in result:
            result["error"] = ctx.clean(result["error"])
        return result

    @router.get("/people-matrix")
    def matrix(
        team: Optional[str] = None,
        window: Optional[str] = None,
        start: Optional[str] = Query(None, alias="from"),
        end: Optional[str] = Query(None, alias="to"),
        include_inactive: bool = False,
    ) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                scope = team_scope(conn, team, include_inactive)
                return people_matrix(
                    conn, scope, _window(ctx, conn, team, window, start, end),
                    history_days=ctx.settings.window_days,
                )
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)

    @router.get("/people")
    def people_list(team: Optional[str] = None, include_inactive: bool = False) -> Dict[str, Any]:
        """Who can be put in focus: a team's members by name, or everyone not excluded when no team is chosen."""
        with _db(ctx) as conn:
            try:
                scope = team_scope(conn, team, include_inactive)
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            people = People(conn)
            if scope.members is None:
                rows = [{"person_id": row["person_id"], "name": row["name"], "status": None} for row in people.all()]
            else:
                rows = [{"person_id": person, "name": people.name(person), "status": status}
                        for person, status in scope.members.items()]
            return {"people": sorted(rows, key=lambda row: row["name"].lower())}

    @router.get("/people/{person_id}")
    def person(
        person_id: str,
        team: Optional[str] = None,
        window: Optional[str] = None,
        start: Optional[str] = Query(None, alias="from"),
        end: Optional[str] = Query(None, alias="to"),
    ) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                scope = team_scope(conn, team)
                return person_detail(conn, person_id, _window(ctx, conn, team, window, start, end), scope)
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)

    @router.get("/person/{person_id}/series")
    def series(
        person_id: str,
        team: Optional[str] = None,
        window_days: int = 30,
        step_days: int = 7,
        history_days: int = 180,
    ) -> Dict[str, Any]:
        if not 7 <= window_days <= 365:
            raise HTTPException(status_code=400, detail="window_days must be between 7 and 365.")
        if not 1 <= step_days <= window_days:
            raise HTTPException(status_code=400, detail="step_days must be between 1 and window_days.")
        if not 0 <= history_days <= 730:
            raise HTTPException(status_code=400, detail="history_days must be between 0 and 730.")
        with _db(ctx) as conn:
            try:
                scope = team_scope(conn, team)
                if conn.execute("SELECT 1 FROM person WHERE person_id = ?", (person_id,)).fetchone() is None:
                    raise LookupError(f"No person with id {person_id!r}.")
                return person_series(
                    conn, person_id, scope, end=ctx.today(), window_days=window_days, step_days=step_days,
                    history_days=history_days, tz=ctx.settings.report_tz,
                    group=comparison.get_group(conn, team) if team else None,
                )
            except LookupError as exc:
                raise _fail(ctx, 404, exc)

    @router.get("/people/{person_id}/export.csv")
    def person_export(
        person_id: str,
        team: Optional[str] = None,
        window: Optional[str] = None,
        start: Optional[str] = Query(None, alias="from"),
        end: Optional[str] = Query(None, alias="to"),
        section: str = "all",
        window_days: int = 30,
    ) -> Response:
        if not 7 <= window_days <= 365:
            raise HTTPException(status_code=400, detail="window_days must be between 7 and 365.")
        with _db(ctx) as conn:
            try:
                scope = team_scope(conn, team)
                row = conn.execute("SELECT display_name FROM person WHERE person_id = ?", (person_id,)).fetchone()
                if row is None:
                    raise LookupError(f"No person with id {person_id!r}.")
                win = _window(ctx, conn, team, window, start, end)
                body = person_csv(
                    conn, person_id, scope, win, section=section, series_end=ctx.today(),
                    window_days=window_days, tz=ctx.settings.report_tz, history_days=ctx.settings.window_days,
                )
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)
        slug = lambda text: re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")  # noqa: E731
        filename = f"{slug(row['display_name']) or 'person'}-metrics-{slug(win.to_json()['label']) or 'window'}.csv"
        return Response(
            content=b"\xef\xbb\xbf" + body.encode("utf-8"), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/tickets")
    def tickets(
        team: Optional[str] = None,
        window: Optional[str] = None,
        start: Optional[str] = Query(None, alias="from"),
        end: Optional[str] = Query(None, alias="to"),
        person: Optional[str] = None,
    ) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                scope = team_scope(conn, team)
                return ticket_costs(conn, scope, _window(ctx, conn, team, window, start, end), person)
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)

    @router.get("/qa")
    def qa() -> Dict[str, Any]:
        with _db(ctx) as conn:
            return qa_dashboard(conn, ctx.today(), ctx.settings.report_tz)

    @router.get("/qa/export.csv")
    def qa_export() -> Response:
        with _db(ctx) as conn:
            body = qa_csv(qa_dashboard(conn, ctx.today(), ctx.settings.report_tz))
        return Response(
            content=b"\xef\xbb\xbf" + body.encode("utf-8"), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="qa-md.csv"'},
        )

    @router.get("/settings")
    def settings() -> Dict[str, Any]:
        return {
            "report_tz": str(ctx.settings.report_tz),
            "window_days": ctx.settings.window_days,
            "overlap_days": ctx.settings.overlap_days,
            "refresh_after_minutes": ctx.settings.refresh_after_minutes,
            "credentials": credential_status(ctx.environ, CREDENTIAL_VARS + CONFIG_VARS),
            "database": str(ctx.db_path),
        }

    @router.post("/teams")
    def create(body: TeamIn) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                repos = []
                for text in body.repos:
                    source, name = parse_repo(text)
                    repos.append((source, resolve_selected(conn, source, name)))
                if not repos:
                    raise ValueError("Choose at least one repository.")
                if not body.name.strip():
                    raise ValueError("A team needs a name.")
                now = utc_now_iso()
                team_id = create_team(conn, body.name.strip(), repos, body.window_days, now=now)
                return {"team_id": team_id, "summary": reconcile_team(conn, team_id, now).summary()}
            except ValueError as exc:
                raise _fail(ctx, 400, exc)

    @router.get("/teams/{team_id}/comparison")
    def comparison_group(team_id: str) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                return comparison.options(conn, team_id)
            except LookupError as exc:
                raise _fail(ctx, 404, exc)

    @router.put("/teams/{team_id}/comparison")
    def set_comparison_group(team_id: str, body: ComparisonIn) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                if body.person_ids is None:
                    comparison.reset_group(conn, team_id)
                else:
                    comparison.set_group(conn, team_id, body.person_ids)
                return comparison.options(conn, team_id)
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)

    @router.post("/teams/{team_id}/members/{person_id}")
    def member(team_id: str, person_id: str, body: MemberIn) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                set_member_status(conn, team_id, person_id, body.status, utc_now_iso())
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)
        return {"team_id": team_id, "person_id": person_id, "status": body.status}

    @router.post("/identities")
    def map_account(body: IdentityIn) -> Dict[str, Any]:
        with _db(ctx) as conn:
            try:
                person_id = map_identity(
                    conn, body.source, body.account, person_id=body.person_id, new_name=body.new_name,
                    team_id=body.team_id, now=utc_now_iso(),
                )
            except LookupError as exc:
                raise _fail(ctx, 404, exc)
            except ValueError as exc:
                raise _fail(ctx, 400, exc)
        return {"person_id": person_id}

    @router.post("/repos")
    def add(body: RepoIn) -> Dict[str, Any]:
        token = (ctx.environ.get("BITBUCKET") or "").strip()
        try:
            source, text = parse_repo(body.repo)
            if source != "bitbucket":
                raise ValueError("Only bitbucket repositories are supported for now. Use bitbucket:<repo>.")
            if not token:
                raise ValueError("BITBUCKET is not set in .env, so repositories cannot be checked or synced.")
            repo = resolve_repository(
                BitbucketClient(token, transport=ctx.transport), text, ctx.settings.bitbucket_workspace
            )
        except (ValueError, BitbucketError) as exc:
            raise _fail(ctx, 400, exc)
        with _db(ctx) as conn:
            add_repo(conn, "bitbucket", repo.uuid, repo.workspace, repo.slug, utc_now_iso())
        return {"repository_id": repo.uuid, "workspace": repo.workspace, "slug": repo.slug}

    @router.delete("/repos/{repository_id}")
    def remove(repository_id: str) -> Dict[str, Any]:
        with _db(ctx) as conn:
            removed = remove_repo(conn, "bitbucket", repository_id)
        if not removed:
            raise HTTPException(status_code=404, detail="No selected repository matches that id.")
        return {"removed": removed}

    @router.post("/refresh")
    def refresh(body: RefreshIn) -> Dict[str, Any]:
        if body.only_stale:
            with _db(ctx) as conn:
                if not _anything_stale(ctx, conn):
                    return {"started": False, "refresh": _refresh_state(ctx)}
        started = ctx.worker.start(body.source, body.full)
        return {"started": started, "refresh": _refresh_state(ctx)}

    return router
