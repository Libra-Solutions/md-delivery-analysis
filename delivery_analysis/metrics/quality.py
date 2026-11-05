"""PR file metrics: how many merged pull requests have tests, and which layers they touch."""

from __future__ import annotations

import re
import sqlite3
from typing import Dict, List, Set

from delivery_analysis.metrics.people import Scope, actor_key
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window

TEST_FILE = re.compile(r"(^|/)[^/]*(test|spec)[^/]*(/|\.|$)", re.IGNORECASE)
FRONT_EXT = (".ts", ".tsx", ".js", ".jsx", ".html", ".scss", ".css")

NO_FILES_NOTE = "{n} merged pull request(s) have no file data yet and are not counted."


def is_test(path: str) -> bool:
    return bool(TEST_FILE.search(path or ""))


def layers_of(path: str) -> str:
    """One of "db", "front", "back", or "" when the file belongs to no layer."""
    low = (path or "").replace("\\", "/").lower()
    if low.endswith(".sql") or low.startswith("database/") or "/database/" in low:
        return "db"
    if low.startswith("movedocs-spa/") or "/movedocs-spa/" in low or low.endswith(FRONT_EXT):
        return "front"
    if low.endswith(".cs"):
        return "back"
    return ""


def _pr_files(conn: sqlite3.Connection, scope: Scope, window: Window):
    """(author, paths) for each merged PR in the window that has file data, plus the count without."""
    where, params = scope.repo_filter("c.repository_id")
    prs = conn.execute(
        "SELECT c.source_id, c.author_account FROM change_request c "
        "WHERE c.source = 'bitbucket' AND c.state = 'MERGED' AND c.merged_at >= ? AND c.merged_at < ? "
        f"AND {where}",
        [window.start, window.end] + params,
    ).fetchall()
    files: Dict[str, Set[str]] = {}
    for row in conn.execute(
        "SELECT v.change_request_id AS pr, f.path FROM vcs_commit v "
        "JOIN commit_file f ON f.repository_id = v.repository_id AND f.sha = v.sha "
        "WHERE v.source = 'bitbucket' AND v.change_request_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM property p WHERE p.record_kind = 'vcs_commit' "
        " AND p.record_id = v.source_id AND p.name = 'is_merge')"
    ):
        files.setdefault(row["pr"], set()).add(row["path"])
    with_files: List = []
    missing = 0
    for pr in prs:
        paths = files.get(pr["source_id"])
        if paths:
            with_files.append((pr["author_account"], sorted(paths)))
        else:
            missing += 1
    return with_files, missing


def _build(conn: sqlite3.Connection, scope: Scope, window: Window, hit) -> Observations:
    obs = Observations()
    rows, missing = _pr_files(conn, scope, window)
    for author, paths in rows:
        obs.add_pair(actor_key(("bitbucket", author)), 1.0 if hit(paths) else 0.0, 1.0)
    if missing:
        obs.notes.append(NO_FILES_NOTE.format(n=missing))
    return obs


def _layers(paths: List[str]) -> Set[str]:
    return {layers_of(p) for p in paths if not is_test(p)} - {""}


def prs_with_tests(conn, scope, window) -> Observations:
    return _build(conn, scope, window, lambda paths: any(is_test(p) for p in paths))


def prs_multi_layer(conn, scope, window) -> Observations:
    return _build(conn, scope, window, lambda paths: len(_layers(paths)) >= 2)


def prs_front_end(conn, scope, window) -> Observations:
    return _build(conn, scope, window, lambda paths: "front" in _layers(paths))


def prs_back_end(conn, scope, window) -> Observations:
    return _build(conn, scope, window, lambda paths: "back" in _layers(paths))


def prs_database(conn, scope, window) -> Observations:
    return _build(conn, scope, window, lambda paths: "db" in _layers(paths))
