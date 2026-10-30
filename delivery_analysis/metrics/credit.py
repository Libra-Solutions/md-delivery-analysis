from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from delivery_analysis.metrics.delivered import DELIVERED_AT_SQL
from delivery_analysis.metrics.people import People, Scope, actor_key
from delivery_analysis.metrics.window import Window

CREDIT_NOTE = (
    "{pr} of {n} completed issue(s) were credited to the authors of their linked pull requests; "
    "{rest} to the assignee because no pull request is linked."
)

CLAUDE_CREDIT_NOTE = (
    "{ev} of {n} completed issue(s) were credited by Claude-era evidence, {pr} to the authors of their linked "
    "pull requests and {rest} to the assignee because no pull request is linked."
)

DEV_CREDIT_NOTE = (
    "{dev} of {n} completed issue(s) were credited to the Dev1/Dev2 fields, {pr} to the authors of their linked "
    "pull requests and {rest} to the assignee because no pull request is linked."
)

CLAUDE_DEV_CREDIT_NOTE = (
    "{dev} of {n} completed issue(s) were credited to the Dev1/Dev2 fields, {ev} by Claude-era evidence, {pr} to "
    "the authors of their linked pull requests and {rest} to the assignee because no pull request is linked."
)

_DEV_SQL = (
    "SELECT record_id, name, value FROM property WHERE record_kind = 'work_item' "
    "AND (name GLOB 'dev1_[0-9]*' OR name GLOB 'dev2_[0-9]*') "
    "AND value IS NOT NULL AND TRIM(value) != '' ORDER BY record_id, name"
)

_DEV_NAME = re.compile(r"^dev[12]_\d+$")  # the field slug plus its numeric id, nothing else

_QA_SQL = (
    "SELECT record_id, name, value FROM property WHERE record_kind = 'work_item' "
    "AND (name GLOB 'qa[12]_[0-9]*' OR name GLOB 'qa_[12]_[0-9]*') "
    "AND value IS NOT NULL AND TRIM(value) != '' ORDER BY record_id, name"
)

_QA_NAME = re.compile(r"^qa_?([12])_\d+$")  # `QA1` and `QA 1` both name a QA slot

_DONE_SQL = (
    "SELECT w.source_id, w.key, w.type, w.assignee_account, w.started_at, " + DELIVERED_AT_SQL + " AS resolved_at, "
    "w.story_points FROM work_item w "
    "JOIN property c ON c.record_kind = 'work_item' AND c.record_id = w.source_id "
    "AND c.name = 'counts_for_impact' AND c.value = '1' "
    "WHERE w.source = 'jira' AND " + DELIVERED_AT_SQL + " >= ? AND " + DELIVERED_AT_SQL + " < ? "
    "ORDER BY " + DELIVERED_AT_SQL + ", w.key"
)
_PR_AUTHORS_SQL = (
    "SELECT DISTINCT l.to_id AS issue_id, c.source_id AS pr_id, c.author_account AS author "
    "FROM link l JOIN change_request c ON c.source = 'bitbucket' AND c.source_id = l.from_id "
    "WHERE l.kind = 'implements' AND l.from_kind = 'change_request' AND l.to_kind = 'work_item' "
    "AND c.author_account IS NOT NULL AND c.author_account != ''"
)
_FIRST_MERGE_SQL = (
    "SELECT l.to_id AS issue_id, MIN(c.merged_at) AS merged_at "
    "FROM link l JOIN change_request c ON c.source = 'bitbucket' AND c.source_id = l.from_id "
    "WHERE l.kind = 'implements' AND l.from_kind = 'change_request' AND l.to_kind = 'work_item' "
    "AND c.state = 'MERGED' AND c.merged_at IS NOT NULL GROUP BY l.to_id"
)


def actor_for(account: Optional[str]) -> Optional[str]:
    """Jira and Bitbucket share one account id, so either identity can resolve the person."""
    return actor_key(("jira", account), ("bitbucket", account))


@dataclass
class Credit:
    """Who gets the credit for each completed issue.

    `issues` are the countable issues completed in the window, oldest first. `shares` maps an issue id to
    `{actor_key: share}` (shares of one issue sum to 1; an empty dict means nobody can be credited).
    `by_pr` holds the issues credited by pull request evidence rather than by assignee; `by_evidence` those
    credited by the Claude-era `ticket_credit` shares (keyed `person:<id>`); `by_dev` those credited by the
    Jira Dev1/Dev2 fields.
    """

    issues: List[sqlite3.Row] = field(default_factory=list)
    shares: Dict[str, Dict[str, float]] = field(default_factory=dict)
    by_pr: Set[str] = field(default_factory=set)
    by_evidence: Set[str] = field(default_factory=set)
    by_dev: Set[str] = field(default_factory=set)


def dev_shares(conn: sqlite3.Connection, issue_ids: Iterable[str]) -> Dict[str, Dict[str, float]]:
    """Shares from the Jira Dev1 and Dev2 fields (properties `dev1_*`, `dev2_*` holding account ids).

    Two different developers get half each; one, or the same one twice, gets the whole issue. Issues
    with neither field set are absent.
    """
    wanted = set(issue_ids)
    if not wanted:
        return {}
    accounts: Dict[str, Dict[str, str]] = {}
    for row in conn.execute(_DEV_SQL):
        if row["record_id"] in wanted and _DEV_NAME.match(row["name"]):
            slot = accounts.setdefault(row["record_id"], {})
            slot.setdefault(row["name"][:4], row["value"].strip())
    return _split(accounts)


def qa_shares(conn: sqlite3.Connection, issue_ids: Iterable[str]) -> Dict[str, Dict[str, float]]:
    """Shares from the Jira QA1 and QA2 fields, split like Dev1 and Dev2. Never part of `credit_for`:
    QA points are their own metric, so developer velocity keeps the Director's rule."""
    wanted = set(issue_ids)
    if not wanted:
        return {}
    accounts: Dict[str, Dict[str, str]] = {}
    for row in conn.execute(_QA_SQL):
        found = _QA_NAME.match(row["name"])
        if row["record_id"] in wanted and found:
            accounts.setdefault(row["record_id"], {}).setdefault(found.group(1), row["value"].strip())
    return _split(accounts)


def _split(accounts: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    """Two different people get half an issue each; one, or the same one twice, gets all of it."""
    shares: Dict[str, Dict[str, float]] = {}
    for issue_id, slots in accounts.items():
        keys = {actor_for(account) for account in slots.values()} - {None}
        if keys:
            shares[issue_id] = {key: 1.0 / len(keys) for key in sorted(keys)}
    return shares


def completed_issues(conn: sqlite3.Connection, window: Window) -> List[sqlite3.Row]:
    return conn.execute(_DONE_SQL, (window.start, window.end)).fetchall()


def credit_for(conn: sqlite3.Connection, window: Window) -> Credit:
    """One credit rule. The Jira Dev1/Dev2 fields win when set; then spec 4's `ticket_credit` shares; then the
    authors of linked pull requests, split by their share of those pull requests; otherwise the assignee."""
    issues = completed_issues(conn, window)
    wanted = {row["source_id"] for row in issues}
    devs = dev_shares(conn, wanted)
    evidence: Dict[str, Dict[str, float]] = {}
    for row in conn.execute("SELECT work_item_source, work_item_id, person_id, share FROM ticket_credit"):
        if row["work_item_source"] == "jira" and row["work_item_id"] in wanted:
            evidence.setdefault(row["work_item_id"], {})[f"person:{row['person_id']}"] = row["share"]
    authors: Dict[str, Counter] = {}
    for row in conn.execute(_PR_AUTHORS_SQL):
        if row["issue_id"] in wanted:
            authors.setdefault(row["issue_id"], Counter())[row["author"]] += 1
    credit = Credit(issues=issues)
    for row in issues:
        issue_id = row["source_id"]
        if devs.get(issue_id):
            credit.shares[issue_id] = devs[issue_id]
            credit.by_dev.add(issue_id)
            continue
        if evidence.get(issue_id):
            credit.shares[issue_id] = evidence[issue_id]
            credit.by_evidence.add(issue_id)
            continue
        counts = authors.get(issue_id)
        if counts:
            total = sum(counts.values())
            credit.shares[issue_id] = {actor_for(account): count / total for account, count in counts.items()}
            credit.by_pr.add(issue_id)
            continue
        key = actor_for(row["assignee_account"])
        credit.shares[issue_id] = {key: 1.0} if key else {}
    return credit


def first_merges(conn: sqlite3.Connection) -> Dict[str, str]:
    """The earliest merge time of the merged pull requests linked to each issue."""
    return {row["issue_id"]: row["merged_at"] for row in conn.execute(_FIRST_MERGE_SQL)}


def credit_note(credit: Credit) -> Optional[str]:
    """Explains how much was credited by evidence rather than by assignee; nothing to say when none was."""
    if not credit.by_pr and not credit.by_evidence and not credit.by_dev:
        return None
    credited = [row for row in credit.issues if credit.shares.get(row["source_id"])]
    dev, pr, ev, n = len(credit.by_dev), len(credit.by_pr), len(credit.by_evidence), len(credited)
    if dev:
        if not ev:
            return DEV_CREDIT_NOTE.format(dev=dev, pr=pr, n=n, rest=n - dev - pr)
        return CLAUDE_DEV_CREDIT_NOTE.format(dev=dev, ev=ev, pr=pr, n=n, rest=n - dev - pr - ev)
    if not ev:
        return CREDIT_NOTE.format(pr=pr, n=n, rest=n - pr)
    return CLAUDE_CREDIT_NOTE.format(ev=ev, pr=pr, n=n, rest=n - pr - ev)


@dataclass
class Scoped:
    """Completed issues for one scope: each with the fraction of it credited inside the scope, those
    nobody can be credited for, and how many were left out because their credit is outside the scope."""

    items: List[Tuple[sqlite3.Row, float]] = field(default_factory=list)
    unassigned: List[sqlite3.Row] = field(default_factory=list)
    outside: int = 0


def scoped(conn: sqlite3.Connection, scope: Scope, credit: Credit) -> Scoped:
    """Under a team only credited members count (an unmapped account or a non-member is outside the
    team); with no team everyone counts, unmapped accounts included. Excluded people never count."""
    people = People(conn)
    result = Scoped()
    for row in credit.issues:
        shares = credit.shares.get(row["source_id"]) or {}
        if not shares:
            result.unassigned.append(row)
            continue
        kept = 0.0
        for key, share in shares.items():
            person = people.resolve(key)
            if person is not None and people.is_excluded(person):
                continue
            if scope.members is not None and person not in scope.members:
                continue
            kept += share
        if kept > 1e-9:
            result.items.append((row, min(kept, 1.0)))
        else:
            result.outside += 1
    return result
