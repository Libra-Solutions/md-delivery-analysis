"""AI uplift API: every number comes from the metrics layer; the pages only draw."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from delivery_analysis.app.api import _db, _fail
from delivery_analysis.app.context import AppContext
from delivery_analysis.metrics import ai_weekly, ai_year, coverage, explain, sprints, uplift, verdicts
from delivery_analysis.metrics.people import People, team_scope
from delivery_analysis.store import cohort, comparison

POINTS = "story_points_done"
GRAPH_TABLES = {
    "story_points_done": ["story_points_done", "issues_done", "impact_points", "delivery_speed"],
    "prs_merged": ["prs_merged", "time_to_merge", "durability", "comments_received_per_pr"],
    "reviews_given": ["reviews_given", "prs_reviewed", "review_value", "review_responsiveness",
                      "participation_points"],
}
YEAR_GRAPHS = ["story_points_done", "prs_merged", "reviews_given"]
QUALITY = ["prs_with_tests", "comments_received_per_pr", "durability", "inline_comments_given"]
WORKED = ["prs_front_end", "prs_back_end", "prs_database", "prs_multi_layer", "reviews_given",
          "inline_comments_given", "teammates_reviewed", "big_tickets"]
THRESHOLDS = {"prs_with_tests": 0.7, "durability": 0.95, "inline_comments_given": 3}
COMMENT_SLACK = 0.2


def _value(window: Dict[str, Any]) -> Optional[float]:
    """A window's number: what happened in it so far (never projected)."""
    return window.get("total")


def _at_or_above_median(graph: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Ended 30-day blocks at or above everyone's median, before and after Day 0 (running blocks are left out)."""
    out = {"before": {"count": 0, "of": 0}, "after": {"count": 0, "of": 0}}
    for block in graph.get("blocks", []):
        if block.get("partial") or block.get("value") is None or block.get("median") is None:
            continue
        side = out["before" if block["index"] < 0 else "after"]
        side["of"] += 1
        if block["value"] >= block["median"]:
            side["count"] += 1
    return out


def _facts(by_metric: Dict[str, Dict[str, Dict[str, Any]]], label: str) -> Dict[str, Any]:
    def win(metric: str) -> Dict[str, Any]:
        return by_metric.get(metric, {}).get(label, {})

    points, comments = win(POINTS), win("comments_received_per_pr")
    # Points are sums over the whole window; the before median is per 30-day block.
    scale = 30.0 / points["days"] if points.get("days") else 1.0

    def per30(number: Optional[float]) -> Optional[float]:
        return None if number is None else round(number * scale, 2)

    return {
        "pace_per30": per30(_value(points)), "before_median": points.get("before_median"),
        "median_per30": per30(points.get("median")),
        "tests_share": _value(win("prs_with_tests")), "durability": _value(win("durability")),
        "comments_per_pr": _value(comments), "before_comments_per_pr": comments.get("before_median"),
        "inline_comments": _value(win("inline_comments_given")), "big_tickets": _value(win("big_tickets")),
    }


def _team_names(conn: Any) -> Dict[str, str]:
    return {row["team_id"]: row["name"]
            for row in conn.execute("SELECT team_id, name FROM team ORDER BY lower(name), team_id")}


def _team_people(conn: Any, team_id: str) -> List[str]:
    """A team's active members who are not excluded (raises LookupError for an unknown team)."""
    people = People(conn)
    return [pid for pid in team_scope(conn, team_id).members or {} if not people.is_excluded(pid)]


def _in_scope(conn: Any, scope: Any) -> List[str]:
    people = People(conn)
    if scope.members is not None:
        return [pid for pid in scope.members if not people.is_excluded(pid)]
    return [row["person_id"] for row in people.all()]


def build_uplift_router(ctx: AppContext) -> APIRouter:
    router = APIRouter(prefix="/api/uplift")

    def member(conn: Any, person_id: str) -> Dict[str, Any]:
        for row in cohort.list_members(conn):
            if row["person_id"] == person_id:
                return row
        raise HTTPException(status_code=404, detail=f"{ctx.clean(person_id)} is not in the cohort.")

    def scope_for(conn: Any, team: Optional[str]) -> Any:
        try:
            return team_scope(conn, team)
        except LookupError as exc:
            raise _fail(ctx, 404, exc)

    def compare_for(conn: Any, compare: Optional[str], scope: Any) -> Any:
        """Resolve `compare=` to (people whose values make the median and average, or None for everyone; info)."""
        value = (compare or "everyone").strip() or "everyone"
        kind, _, key = value.partition(":")
        used = _in_scope(conn, scope)
        note = None
        group: Optional[List[str]] = None
        label = "Everyone"
        chosen = 0
        try:
            if value == "everyone":
                pass
            elif kind == "team" and key:
                group = _team_people(conn, key)
                label = _team_names(conn).get(key) or key
            elif kind == "group" and key:
                name = _team_names(conn).get(key)
                saved = comparison.get_group(conn, key)
                label = f"{name or key} comparison group"
                if saved is None:
                    group = _team_people(conn, key)
                    note = f"No comparison group is saved for {name or key}, so the whole team is used."
                else:
                    group = saved
            elif value == "cohort":
                label = "My direct reports"
                group = [row["person_id"] for row in cohort.list_members(conn)]
            elif kind == "people":
                group = list(dict.fromkeys(part.strip() for part in key.split(",") if part.strip()))
                if not group:
                    raise HTTPException(status_code=400, detail="Pick at least one person to compare against.")
                known = {row["person_id"] for row in People(conn).all()}
                bad = [pid for pid in group if pid not in known]
                if bad:
                    raise HTTPException(status_code=400, detail=ctx.clean(
                        f"Unknown or excluded people in compare: {', '.join(bad)}."))
                label = f"{len(group)} chosen people"
                chosen = len(group)
            else:
                raise HTTPException(status_code=400, detail=ctx.clean(
                    f"Unknown compare value {value!r}. Use everyone, team:<id>, group:<id>, people:<ids> or cohort."))
        except LookupError as exc:
            raise _fail(ctx, 404, exc)
        if group is None:
            return None, {"value": value, "label": label, "size": len(used)}
        wanted = set(group)
        size = len([pid for pid in used if pid in wanted])
        if size == 0:
            extra = f"Nobody in {label} is in the selected scope, so everyone is used."
            note = f"{note} {extra}" if note else extra
            size = len(used)
        elif kind == "people":
            size = chosen
        info: Dict[str, Any] = {"value": value, "label": label, "size": size}
        if note:
            info["note"] = note
        return group, info

    @router.get("/compare-options")
    def compare_options() -> Dict[str, Any]:
        with _db(ctx) as conn:
            options = [{"value": "everyone", "label": "Everyone", "size": len(People(conn).all())}]
            for team_id, name in _team_names(conn).items():
                people = _team_people(conn, team_id)
                saved = comparison.get_group(conn, team_id)
                options.append({"value": f"team:{team_id}", "label": name, "size": len(people)})
                options.append({"value": f"group:{team_id}", "label": f"{name} comparison group",
                                "size": len(people) if saved is None else len(saved)})
            options.append({"value": "cohort", "label": "My direct reports", "size": len(cohort.list_members(conn))})
            options.append({"value": "people:", "label": "Custom people…", "size": None})
            return {"options": options}

    @router.get("/cohort")
    def cohort_view(team: Optional[str] = None, compare: Optional[str] = None) -> Dict[str, Any]:
        today, tz = ctx.today(), ctx.settings.report_tz
        with _db(ctx) as conn:
            scope = scope_for(conn, team)
            group, info = compare_for(conn, compare, scope)
            people = []
            for row in cohort.list_members(conn):
                day0 = date.fromisoformat(row["day0"])
                graph = uplift.person_blocks(conn, row["person_id"], scope, POINTS, day0, today, tz, group=group)
                people.append({**row, "day_reached": (today - day0).days, "points": graph,
                               "grid": graph.get("blocks", []),
                               "at_or_above_median": _at_or_above_median(graph)})
            return {"coverage": coverage.data_coverage(conn), "compare": info, "people": people}

    @router.get("/person/{person_id}")
    def person_view(person_id: str, team: Optional[str] = None, compare: Optional[str] = None) -> Dict[str, Any]:
        today, tz = ctx.today(), ctx.settings.report_tz
        with _db(ctx) as conn:
            row = member(conn, person_id)
            scope = scope_for(conn, team)
            group, info = compare_for(conn, compare, scope)
            day0 = date.fromisoformat(row["day0"])

            def blocks(metric: str) -> Dict[str, Any]:
                return uplift.person_blocks(conn, person_id, scope, metric, day0, today, tz, group=group)

            graphs = {
                metric: {"blocks": blocks(metric),
                         "table": uplift.metric_table(conn, person_id, scope, names, day0, today, tz, group=group)}
                for metric, names in GRAPH_TABLES.items()
            }
            graphs[POINTS]["blocks"] = {**graphs[POINTS]["blocks"],
                                        "at_or_above_median": _at_or_above_median(graphs[POINTS]["blocks"])}
            windows = uplift.windows(conn, person_id, scope, POINTS, day0, today, tz, group=group)
            by_metric: Dict[str, Dict[str, Dict[str, Any]]] = {POINTS: {w["label"]: w for w in windows}}
            worked = {}
            for metric in sorted(set(WORKED + QUALITY) - {POINTS}):
                found = uplift.windows(conn, person_id, scope, metric, day0, today, tz, group=group)
                by_metric[metric] = {w["label"]: w for w in found}
                worked[metric] = found
            quality = []
            for metric in QUALITY:
                graph = blocks(metric)
                threshold = THRESHOLDS.get(metric)
                if metric == "comments_received_per_pr":
                    before = (graph.get("person", {}).get("before") or {}).get("median")
                    threshold = None if before is None else before + COMMENT_SLACK
                quality.append({"metric": metric, "blocks": graph, "threshold": threshold})
            verdict_rows: List[Dict[str, Any]] = [
                {"label": w["label"],
                 "items": verdicts.verdicts(row["level"], w["label"], _facts(by_metric, w["label"]))}
                for w in windows if w["complete"]  # a running window would need a projection
            ]
            ai_start = day0 - timedelta(days=90)
            return {
                "person": {"person_id": person_id, "name": row["name"]},
                "level": row["level"], "day0": row["day0"], "day_reached": (today - day0).days,
                "coverage": coverage.data_coverage(conn), "compare": info, "graphs": graphs,
                "points_by_merge": blocks("points_by_merge_date"), "windows": windows,
                "verdicts": verdict_rows, "quality": quality,
                "how_they_worked": {m: worked[m] for m in WORKED},
                "ai": ai_weekly.weekly(conn, person_id, ai_start, today, tz),
                "explain": explain.explain(conn, person_id, day0, today, graphs[POINTS]["blocks"]),
            }

    @router.get("/year/people")
    def year_people() -> Dict[str, Any]:
        with _db(ctx) as conn:
            start_of_data = ai_year.claude_data_start(conn)
            people = []
            for row in cohort.list_members(conn):
                start = ai_year.ai_start(conn, row["person_id"])
                people.append({"person_id": row["person_id"], "name": row["name"], "level": row["level"],
                               "ai_start": start.isoformat() if start else None,
                               "at_data_start": bool(start and start == start_of_data)})
            return {"claude_data_start": start_of_data.isoformat() if start_of_data else None, "people": people}

    @router.get("/year/person/{person_id}")
    def year_person(person_id: str, team: Optional[str] = None, compare: Optional[str] = None,
                    by: str = "month") -> Dict[str, Any]:
        if by not in ("month", "sprint"):
            raise HTTPException(status_code=400, detail="by must be month or sprint.")
        today, tz = ctx.today(), ctx.settings.report_tz
        with _db(ctx) as conn:
            row = member(conn, person_id)
            scope = scope_for(conn, team)
            group, info = compare_for(conn, compare, scope)
            start = ai_year.ai_start(conn, person_id)
            start_of_data = ai_year.claude_data_start(conn)
            layout, first, board = None, None, None
            if by == "sprint":
                board_id = sprints.person_board(conn, person_id, today - timedelta(days=sprints.YEAR_DAYS))
                layout = [] if board_id is None else sprints.sprint_blocks(conn, board_id, today, start)
                if board_id is not None:
                    board = {"board_id": board_id, "name": sprints.board_name(conn, board_id)}
                if layout:
                    first = date.fromisoformat(layout[0]["first"])
            graphs = {metric: ai_year.person_months(conn, person_id, scope, metric, start, today, tz, group=group,
                                                    layout=layout)
                      for metric in YEAR_GRAPHS}
            unit = "sprint" if by == "sprint" else "month"
            notes = [f"The {unit} of the AI start counts as since AI."]
            if by == "sprint":
                if board is None:
                    notes.insert(0, "None of this person's tickets are in a sprint, so there are no sprints to show.")
                else:
                    notes.insert(0, f"Sprints of the {board['name']} board, where most of their tickets were "
                                    "sprinted. Everyone in the comparison is measured over the same sprints.")
            if start is None:
                notes = [n for n in notes if "AI start" not in n] + [
                    "No Claude use is linked to this person, so the year is shown without a before and after "
                    "split. Link their Claude account on the Teams screen."]
            elif start == start_of_data:
                notes.append(f"Their first Claude use is the first day of Claude data ({start.isoformat()}), "
                             "so they may have started earlier.")
            return {
                "person": {"person_id": person_id, "name": row["name"]}, "level": row["level"],
                "ai_start": start.isoformat() if start else None,
                "at_data_start": bool(start and start == start_of_data),
                "by": by, "board": board,
                "coverage": coverage.data_coverage(conn), "compare": info, "graphs": graphs,
                "expectations": [] if by == "sprint" and not layout else ai_year.expectations(
                    conn, person_id, scope, row["level"], start, today, tz, graphs[POINTS], group=group,
                    who=info["label"], first=first, unit=unit),
                "notes": notes,
            }

    return router
