"""Builds the stored impact values: pull request value, fixed review comments and per-person shares.

Everything is derived from synced tables (completed Jira issues, linked pull requests, commit files, review
comments and the code graph) and the three derived tables are replaced whole in one transaction, so a rebuild
is repeatable. The model and the coordinator decisions are in the code-weighted impact design spec.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Dict, List, Optional, Set, Tuple

from delivery_analysis.metrics.credit import actor_for, dev_shares
from delivery_analysis.metrics.delivered import DELIVERED_AT_SQL

REVIEWER_RATE = 0.05
OWNER_RATE = 0.005
FIX_WINDOW_LINES = 10
BASELINE_DAYS = 90
BASELINE_MIN_TICKETS = 5
_STAMP = "%Y-%m-%dT%H:%M:%SZ"

_COHORT_SQL = (
    "SELECT w.source_id, w.assignee_account, " + DELIVERED_AT_SQL + " AS resolved_at, w.story_points "
    "FROM work_item w "
    "JOIN property c ON c.record_kind = 'work_item' AND c.record_id = w.source_id "
    "AND c.name = 'counts_for_impact' AND c.value = '1' "
    "WHERE w.source = 'jira' AND " + DELIVERED_AT_SQL + " IS NOT NULL "
    "AND w.story_points IS NOT NULL ORDER BY " + DELIVERED_AT_SQL + ", w.source_id"
)
_PRS_SQL = (
    "SELECT DISTINCT l.to_id AS issue_id, c.source_id AS pr_id, c.repository_id AS repo, "
    "c.author_account AS author, c.merged_at AS merged_at, c.closed_at AS closed_at "
    "FROM link l JOIN change_request c ON c.source = 'bitbucket' AND c.source_id = l.from_id "
    "WHERE l.kind = 'implements' AND l.from_kind = 'change_request' AND l.to_kind = 'work_item'"
)
_COMMITS_SQL = (
    "SELECT v.change_request_id AS pr_id, v.repository_id AS repo, v.sha AS sha, v.committed_at AS at, "
    "COALESCE(p.value, '0') AS is_merge FROM vcs_commit v "
    "LEFT JOIN property p ON p.record_kind = 'vcs_commit' AND p.record_id = v.source_id AND p.name = 'is_merge' "
    "WHERE v.source = 'bitbucket' AND v.change_request_id IS NOT NULL"
)
_FILES_SQL = (
    "SELECT v.change_request_id AS pr_id, v.sha AS sha, f.path AS path, f.hunks AS hunks "
    "FROM vcs_commit v JOIN commit_file f ON f.repository_id = v.repository_id AND f.sha = v.sha "
    "WHERE v.source = 'bitbucket' AND v.change_request_id IS NOT NULL"
)
_COMMENTS_SQL = (
    "SELECT source_id, change_request_id AS pr_id, actor_account, created_at, path, line, resolved "
    "FROM review_comment WHERE parent_id IS NULL AND actor_account IS NOT NULL AND actor_account != '' "
    "AND created_at IS NOT NULL ORDER BY created_at, source_id"
)
_REPLIES_SQL = "SELECT DISTINCT parent_id, actor_account FROM review_comment WHERE parent_id IS NOT NULL"


@dataclass(frozen=True)
class ImpactSummary:
    tickets: int = 0
    prs_valued: int = 0
    prs_without_files: int = 0
    fixes: int = 0

    def lines(self) -> List[str]:
        return [
            f"Impact: {self.tickets} completed ticket(s) with story points weighed.",
            f"{self.prs_valued} pull request(s) valued, {self.prs_without_files} without file data, "
            f"{self.fixes} fixed review comment(s).",
        ]


@dataclass
class _Pr:
    pr_id: str
    repo: Optional[str]
    author: Optional[str]
    end: Optional[str]
    files: Set[str]
    scope: float = 0.0
    value: float = 0.0


class _Weights:
    """File weights from the code graph; r(f) is the weight over the repository's median code-file weight."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.w: Dict[Tuple[str, str], float] = {}
        by_repo: Dict[str, List[float]] = defaultdict(list)
        for row in conn.execute("SELECT repository_id, path, weight FROM code_file"):
            self.w[(row["repository_id"], row["path"])] = float(row["weight"])
            if row["weight"] >= 1:
                by_repo[row["repository_id"]].append(float(row["weight"]))
        self.median = {repo: median(values) for repo, values in by_repo.items()}

    def weight(self, repo: Optional[str], path: str) -> float:
        return self.w.get((repo, path), 1.0)  # a file the graph never saw counts as an ordinary code file

    def relative(self, repo: Optional[str], path: str) -> float:
        return self.weight(repo, path) / (self.median.get(repo) or 1.0)


def _minus_days(stamp: str, days: int) -> str:
    return (datetime.strptime(stamp, _STAMP) - timedelta(days=days)).strftime(_STAMP)


def _near(hunks: List[List[int]], line: int) -> bool:
    return any(start - FIX_WINDOW_LINES <= line <= end + FIX_WINDOW_LINES for start, end in hunks)


def _load_prs(conn: sqlite3.Connection, cohort: List[sqlite3.Row]):
    """Pull requests per ticket; one that links several tickets belongs to the earliest resolved."""
    order = {row["source_id"]: index for index, row in enumerate(cohort)}
    delivered = {row["source_id"]: row["resolved_at"] for row in cohort}
    chosen: Dict[str, sqlite3.Row] = {}
    for row in conn.execute(_PRS_SQL):
        if row["issue_id"] not in order:
            continue
        current = chosen.get(row["pr_id"])
        if current is None or order[row["issue_id"]] < order[current["issue_id"]]:
            chosen[row["pr_id"]] = row
    files: Dict[str, Set[str]] = defaultdict(set)
    for row in conn.execute(_FILES_SQL):
        if row["pr_id"] in chosen:
            files[row["pr_id"]].add(row["path"])
    by_issue: Dict[str, List[_Pr]] = defaultdict(list)
    for pr_id in sorted(chosen):
        row = chosen[pr_id]
        by_issue[row["issue_id"]].append(
            _Pr(
                pr_id, row["repo"], row["author"],
                # an open pull request is cut off at the ticket's delivered date, so later work never counts
                row["merged_at"] or row["closed_at"] or delivered.get(row["issue_id"]),
                files.get(pr_id, set()),
            )
        )
    return by_issue


def _load_commits(conn: sqlite3.Connection, wanted: Set[str]):
    commits: Dict[str, List[Tuple[str, str, Dict[str, List[List[int]]]]]] = defaultdict(list)
    index: Dict[Tuple[str, str], Dict[str, List[List[int]]]] = {}
    for row in conn.execute(_FILES_SQL):
        if row["pr_id"] in wanted:
            try:
                hunks = json.loads(row["hunks"] or "[]")
            except ValueError:
                hunks = []
            index.setdefault((row["pr_id"], row["sha"]), {})[row["path"]] = hunks
    for row in conn.execute(_COMMITS_SQL):
        if row["pr_id"] in wanted and row["at"] and str(row["is_merge"]).strip() not in ("1", "true", "True"):
            commits[row["pr_id"]].append((row["at"], row["sha"], index.get((row["pr_id"], row["sha"]), {})))
    for pr_commits in commits.values():
        pr_commits.sort(key=lambda item: (item[0], item[1]))
    return commits


def _fix_for(comment: sqlite3.Row, pr: _Pr, commits, owner_replied: bool = False) -> Optional[str]:
    """The sha of the first commit on the PR that fixes the comment, or None. An inline comment needs a later
    change near its line; a general one needs a later commit and either a resolved mark or a reply from the
    PR author (Bitbucket general comments are rarely marked resolved)."""
    for at, sha, files in commits:
        if at <= comment["created_at"] or (pr.end is not None and at >= pr.end):
            continue
        if comment["path"]:
            hunks = files.get(comment["path"])
            if hunks is None:
                continue
            if comment["line"] is None or _near(hunks, int(comment["line"])):
                return sha
        elif comment["resolved"] or owner_replied:
            return sha
    return None


def _write(conn: sqlite3.Connection, now: str, pr_rows, fix_rows, share_rows) -> None:
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        for table in ("pr_value", "comment_fix", "impact_share"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            "INSERT INTO pr_value (pr_id, issue_id, scope, value, has_files, built_at) VALUES (?, ?, ?, ?, ?, ?)",
            [row + (now,) for row in pr_rows],
        )
        conn.executemany(
            "INSERT INTO comment_fix (comment_id, pr_id, reviewer_key, owner_key, path, rel_weight, "
            "reviewer_credit, owner_penalty, fix_sha) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", fix_rows,
        )
        conn.executemany(
            "INSERT INTO impact_share (issue_id, actor_key, resolved_at, delivery, participation, penalty, "
            "scope_factor, value, built_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [row + (now,) for row in share_rows],
        )
        if own:
            conn.execute("COMMIT")
    except Exception:
        if own:
            conn.execute("ROLLBACK")
        raise


def rebuild_impact(conn: sqlite3.Connection, now: str) -> ImpactSummary:
    """Recompute pr_value, comment_fix and impact_share for every completed ticket with story points."""
    cohort = conn.execute(_COHORT_SQL).fetchall()
    prs_by_issue = _load_prs(conn, cohort)
    weights = _Weights(conn)
    all_prs = {pr.pr_id: pr for prs in prs_by_issue.values() for pr in prs}
    commits = _load_commits(conn, {pr_id for pr_id, pr in all_prs.items() if pr.files})

    # Ticket scope: the distinct files of every linked PR that has file data. Without any, the ticket falls back.
    scoped: Dict[str, float] = {}
    for issue_id, prs in prs_by_issue.items():
        with_files = [pr for pr in prs if pr.files]
        for pr in with_files:
            pr.scope = sum(weights.weight(pr.repo, path) for path in pr.files)
        union = {(pr.repo, path) for pr in with_files for path in pr.files}
        total = sum(weights.weight(repo, path) for repo, path in union)
        if sum(pr.scope for pr in with_files) > 0 and total > 0:
            scoped[issue_id] = total
    resolved = {row["source_id"]: row["resolved_at"] for row in cohort}
    devs = dev_shares(conn, resolved)

    pr_rows: List[tuple] = []
    fix_rows: List[tuple] = []
    shares: Dict[Tuple[str, str], Dict[str, float]] = {}
    comments_by_pr: Dict[str, List[sqlite3.Row]] = defaultdict(list)
    for row in conn.execute(_COMMENTS_SQL):
        comments_by_pr[row["pr_id"]].append(row)
    replies = {(row["parent_id"], row["actor_account"]) for row in conn.execute(_REPLIES_SQL)}

    def share(issue_id: str, key: str, **parts: float) -> None:
        entry = shares.setdefault((issue_id, key), {"delivery": 0.0, "participation": 0.0, "penalty": 0.0})
        for name, value in parts.items():
            entry[name] += value

    factors: Dict[str, float] = {}
    values: Dict[str, float] = {}
    for issue in cohort:
        issue_id, points = issue["source_id"], float(issue["story_points"])
        prs = prs_by_issue.get(issue_id, [])
        assignee = actor_for(issue["assignee_account"])
        if issue_id not in scoped:
            factors[issue_id], values[issue_id] = 1.0, points
            for pr in prs:
                pr_rows.append((pr.pr_id, issue_id, None, points / len(prs), 1 if pr.files else 0))
            for owner, fraction in (devs.get(issue_id) or ({assignee: 1.0} if assignee else {})).items():
                share(issue_id, owner, delivery=points * fraction)
            continue
        window_start = _minus_days(issue["resolved_at"], BASELINE_DAYS)
        baseline = [
            scope for other, scope in scoped.items()
            if window_start <= resolved[other] < issue["resolved_at"]
        ]
        factor = scoped[issue_id] / median(baseline) if len(baseline) >= BASELINE_MIN_TICKETS else 1.0
        factors[issue_id], values[issue_id] = factor, points * factor
        with_files = [pr for pr in prs if pr.files]
        filler = mean(pr.scope for pr in with_files)
        for pr in prs:
            if not pr.files:
                pr.scope = filler
        total_scope = sum(pr.scope for pr in prs)
        for pr in prs:
            pr.value = values[issue_id] * pr.scope / total_scope
            pr_rows.append((pr.pr_id, issue_id, pr.scope, pr.value, 1 if pr.files else 0))
            owner = actor_for(pr.author) or assignee
            penalty = 0.0
            credits: Dict[str, float] = defaultdict(float)
            relative = [weights.relative(pr.repo, path) for path in sorted(pr.files)]
            for comment in comments_by_pr.get(pr.pr_id, []):
                reviewer = actor_for(comment["actor_account"])
                if comment["actor_account"] == pr.author or not reviewer or reviewer == owner or not pr.files:
                    continue
                replied = not comment["path"] and (comment["source_id"], pr.author) in replies
                sha = _fix_for(comment, pr, commits.get(pr.pr_id, []), replied)
                if sha is None:
                    continue
                r = weights.relative(pr.repo, comment["path"]) if comment["path"] else mean(relative)
                credit, cost = REVIEWER_RATE * pr.value * r, OWNER_RATE * pr.value * r
                penalty += cost
                credits[reviewer] += credit
                fix_rows.append((comment["source_id"], pr.pr_id, reviewer, owner, comment["path"], r, credit, cost, sha))
            if owner:
                share(issue_id, owner, delivery=max(0.0, pr.value - penalty), penalty=penalty)
            for reviewer, credit in credits.items():
                share(issue_id, reviewer, participation=min(credit, pr.value))  # reviewer cap: <= V(p) per PR

    share_rows = [
        (issue_id, key, resolved[issue_id], parts["delivery"], parts["participation"], parts["penalty"],
         factors[issue_id], values[issue_id])
        for (issue_id, key), parts in sorted(shares.items())
    ]
    _write(conn, now, sorted(pr_rows), sorted(fix_rows), share_rows)
    return ImpactSummary(
        tickets=len(cohort),
        prs_valued=len(pr_rows),
        prs_without_files=sum(1 for row in pr_rows if not row[4]),
        fixes=len(fix_rows),
    )
