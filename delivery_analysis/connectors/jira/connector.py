from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set
from zoneinfo import ZoneInfo

from delivery_analysis.connectors.jira import normalize
from delivery_analysis.connectors.jira.client import (
    AuthError,
    BudgetExhausted,
    ForbiddenError,
    JiraClient,
    JiraError,
    NotFoundError,
)
from delivery_analysis.connectors.jira.fields import SEARCH_FIELDS, FieldCatalogue, points_value
from delivery_analysis.connectors.jira.jql import ACCOUNT_ID, developer_jql, project_jql
from delivery_analysis.connectors.jira.statuses import SEED
from delivery_analysis.model.records import Batch, RawPayload, Record
from delivery_analysis.store.db import connect
from delivery_analysis.store import project_selection
from delivery_analysis.sync.runner import utc_now_iso
from delivery_analysis.teams.discover import window_start

SOURCE = "jira"
STATUS_FIELDS = ["status"]
DEVELOPERS_SCOPE = "developers"  # Jira project keys are upper case, so this never collides with one
DEV_FIELD_NAMES = ("Dev1", "Dev2")
QA_FIELD_NAMES = ("QA1", "QA2", "QA 1", "QA 2")  # testers' tickets feed the QA points metric
POINTS_FALLBACK_NAME = "Story point estimate"
DEFAULT_EXCLUDED_TYPES = "Epic,Initiative"
UNSEEDED_CATEGORY = "todo"

log = logging.getLogger(__name__)


def credential_problems(client: JiraClient) -> List[str]:
    """Plain-language problems with the Jira credentials; empty means they work."""
    if not client.email:
        return [
            "ATLASSIAN_EMAIL is not set. Put the Atlassian account email in .env as ATLASSIAN_EMAIL "
            "(or write ATLASSIAN as email:token)."
        ]
    try:
        me = client.myself()
    except AuthError as exc:
        return [str(exc)]
    except ForbiddenError:
        return ["The token is missing the read:jira-user permission."]
    except NotFoundError:
        return [
            "Jira did not find the site. Check JIRA_BASE_URL; a scoped token needs the "
            "https://api.atlassian.com/ex/jira/<cloudId> form."
        ]
    except JiraError as exc:
        return [str(exc)]
    if not isinstance(me, dict) or not me.get("accountId"):
        return [
            "Jira answered without an account. Check JIRA_BASE_URL; a scoped token needs the "
            "https://api.atlassian.com/ex/jira/<cloudId> form."
        ]
    return []


class JiraConnector:
    name = SOURCE

    def __init__(
        self,
        client: JiraClient,
        db_path: Path,
        *,
        window_days: int = 90,
        now: Callable[[], str] = utc_now_iso,
        max_pages: int = 500,
    ) -> None:
        self._client = client
        self._db_path = db_path
        self._window_days = window_days
        self._now = now
        self._max_pages = max_pages
        self._tz: Optional[ZoneInfo] = None
        self.unknown_statuses: Set[str] = set()
        self.notices: List[str] = []

    # --- selection -------------------------------------------------------------------------

    def _selected(self) -> List[Dict[str, str]]:
        conn = connect(self._db_path)
        try:
            return project_selection.list_projects(conn, SOURCE)
        except sqlite3.OperationalError:
            return []  # database not migrated yet
        finally:
            conn.close()

    def scopes(self) -> List[str]:
        keys = sorted(row["project_key"] for row in self._selected())
        return keys + [DEVELOPERS_SCOPE] if keys else keys

    def _project(self, scope: str) -> Dict[str, str]:
        for row in self._selected():
            if row["project_key"] == scope:
                return row
        raise JiraError(f"Project {scope} is not selected. Run: delivery-analysis projects add jira:{scope}")

    def _status_map(self, scope: str) -> Dict[str, str]:
        conn = connect(self._db_path)
        try:
            return project_selection.status_map(conn, SOURCE, scope)
        finally:
            conn.close()

    # --- validation ------------------------------------------------------------------------

    def validate(self) -> List[str]:
        if not self._selected():
            return []
        return credential_problems(self._client)

    # --- sync ------------------------------------------------------------------------------

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
        self.notices = []
        try:
            if scope == DEVELOPERS_SCOPE:
                yield from self._sync_developers(since)
            else:
                yield from self._sync_project(scope, self._project(scope), since)
        except BudgetExhausted:
            return  # the run budget is used up; the next sync continues from the last committed page

    def _timezone(self) -> ZoneInfo:
        if self._tz is None:
            name = (self._client.myself() or {}).get("timeZone") or "UTC"
            try:
                self._tz = ZoneInfo(name)
            except Exception:
                self._tz = ZoneInfo("UTC")
        return self._tz

    def _precheck(self, scope: str, status_map: Dict[str, str]) -> None:
        names = {
            status["name"]
            for issue_type in self._client.project_statuses(scope)
            for status in issue_type.get("statuses", [])
        }
        missing = sorted(name for name in names if name not in status_map)
        if missing:
            listed = ", ".join(repr(name) for name in missing)
            raise JiraError(
                f"Project {scope} has statuses with no mapping: {listed}. Map each with: "
                f'delivery-analysis projects map jira:{scope} "<status>" '
                "<todo|in_progress|in_review|done|dropped>"
            )

    def _histories(self, issue_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        by_issue: Dict[str, List[Dict[str, Any]]] = {}
        for page in self._client.changelog_pages(issue_ids, STATUS_FIELDS):
            for entry in page.get("issueChangeLogs", []):
                by_issue.setdefault(str(entry["issueId"]), []).extend(entry.get("changeHistories", []))
        return by_issue

    def _sync_project(self, scope: str, project: Dict[str, str], since: Optional[str]) -> Iterator[Batch]:
        status_map = self._status_map(scope)
        self._precheck(scope, status_map)
        catalogue = FieldCatalogue(self._client.fields())
        tz = self._timezone()
        started = self._now()
        cutoff = since or window_start(started, self._window_days)
        jql = project_jql(scope, cutoff, tz)

        def convert(issue: Dict[str, Any], history: List[Dict[str, Any]]) -> Optional[normalize.IssueResult]:
            return normalize.issue_records(issue, project, status_map, catalogue, history)

        yield from self._pages(scope, jql, convert)

    def _pages(
        self,
        scope: str,
        jql: str,
        convert: Callable[[Dict[str, Any], List[Dict[str, Any]]], Optional[normalize.IssueResult]],
    ) -> Iterator[Batch]:
        """One batch per search page; `convert` returns None to skip an issue."""
        token: Optional[str] = None
        seen: Set[str] = set()
        pages = 0
        while True:
            if pages >= self._max_pages:
                raise JiraError(f"Jira returned more than {self._max_pages} pages for {scope}; stopping.")
            page = self._client.search(jql, SEARCH_FIELDS, token)
            issues = page.get("issues") or []
            if not issues:
                return
            pages += 1
            histories = self._histories([str(issue["id"]) for issue in issues])
            records: List[Record] = []
            raws: List[RawPayload] = []
            updated: List[str] = []
            for issue in issues:
                result = convert(issue, histories.get(str(issue["id"]), []))
                if result is None:
                    continue
                records.extend(result.records)
                raws.append(result.raw)
                self.unknown_statuses.update(result.unknown_statuses)
                if result.updated:
                    updated.append(result.updated)
            yield Batch(records, raws, cursor=max(updated) if updated else None)
            token = page.get("nextPageToken")
            if not token or token in seen:
                return
            seen.add(token)

    # --- developer scope -------------------------------------------------------------------

    def _team_accounts(self) -> List[str]:
        """Account ids of active team members (bitbucket and jira identities) fit for JQL."""
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT i.account_id AS account_id FROM identity i "
                "JOIN team_member m ON m.person_id = i.person_id "
                "WHERE m.status = 'active' AND i.source IN ('bitbucket', 'jira') "
                "ORDER BY i.account_id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # database not migrated yet
        finally:
            conn.close()
        return [row["account_id"] for row in rows if ACCOUNT_ID.match(row["account_id"] or "")]

    def _note(self, message: str) -> None:
        self.notices.append(message)
        log.info("%s/%s: %s", SOURCE, DEVELOPERS_SCOPE, message)

    def _sync_developers(self, since: Optional[str]) -> Iterator[Batch]:
        selected = self._selected()
        if not selected:
            self._note("No Jira project is selected, so there is nothing to look up by developer.")
            return
        accounts = self._team_accounts()
        if not accounts:
            self._note("No active team member has a Jira or Bitbucket account yet, so no developer tickets were fetched.")
            return
        catalogue = FieldCatalogue(self._client.fields())
        dev_fields = [fid for name in DEV_FIELD_NAMES + QA_FIELD_NAMES for fid in catalogue.ids_by_name(name)]
        if not dev_fields:
            self._note("This Jira site has no Dev1, Dev2, QA1 or QA2 field, so no developer tickets were fetched.")
            return
        tz = self._timezone()
        cutoff = since or window_start(self._now(), self._window_days)
        keys = sorted(row["project_key"] for row in selected)
        jql = developer_jql(dev_fields, accounts, keys, cutoff, tz)
        points_fields = self._points_fields(selected, catalogue)
        excluded = set(keys)

        def convert(issue: Dict[str, Any], history: List[Dict[str, Any]]) -> Optional[normalize.IssueResult]:
            fields = issue.get("fields") or {}
            own = (fields.get("project") or {}).get("key")
            if own in excluded:
                return None  # a selected project's own sync owns it
            project = {
                "project_key": own,
                "story_points_field": next(
                    (f for f in points_fields if points_value(fields.get(f)) is not None),
                    points_fields[0] if points_fields else None,
                ),
                "excluded_types": DEFAULT_EXCLUDED_TYPES,
            }
            status_map = self._developer_status_map(fields, history)
            return normalize.issue_records(issue, project, status_map, catalogue, history)

        yield from self._pages(DEVELOPERS_SCOPE, jql, convert)

    @staticmethod
    def _points_fields(selected: List[Dict[str, str]], catalogue: FieldCatalogue) -> List[str]:
        """The points field the selected projects use (most common first), then the site's estimate fields."""
        used = Counter(row["story_points_field"] for row in selected if row.get("story_points_field"))
        ordered = [field for field, _ in sorted(used.items(), key=lambda item: (-item[1], item[0]))]
        for field in catalogue.ids_by_name(POINTS_FALLBACK_NAME):
            if field not in ordered:
                ordered.append(field)
        return ordered

    def _developer_status_map(self, fields: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, str]:
        """SEED by name; a name outside it is reported and kept as `todo`, which never counts as delivered."""
        names = {(fields.get("status") or {}).get("name")}
        for transition in normalize.status_transitions(history):
            names.update((transition.from_status, transition.to_status))
        mapping = dict(SEED)
        for name in names:
            if name and name not in SEED:
                mapping[name] = UNSEEDED_CATEGORY
                self.unknown_statuses.add(name)
        return mapping
