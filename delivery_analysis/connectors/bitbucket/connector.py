from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set
from urllib.parse import quote

from delivery_analysis.connectors.bitbucket import normalize
from delivery_analysis.connectors.bitbucket.client import (
    AuthError,
    BitbucketClient,
    BitbucketError,
    BudgetExhausted,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
)
from delivery_analysis.core.time_utils import to_utc_iso
from delivery_analysis.model.records import Batch, RawPayload, Record
from delivery_analysis.store.db import connect
from delivery_analysis.store.repo_selection import list_selected
from delivery_analysis.sync.runner import utc_now_iso
from delivery_analysis.teams.discover import window_start

SOURCE = "bitbucket"
PR_STATES = ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
# Requests kept back per repository still to sync, so one repository's detail backlog
# cannot use the whole run budget before the next repository's list stages.
RESERVE_PER_REPO = 10
# Live Bitbucket rejects pagelen above 50 on the pull request list and its activity (HTTP 400).
PR_PAGELEN = 50
COMMIT_FIELDS = (
    "next,values.hash,values.date,values.author.raw,values.author.user.account_id,values.parents.hash"
)
PR_FIELDS = (
    "next,values.id,values.title,values.state,values.author.account_id,values.source.branch.name,"
    "values.created_on,values.updated_on,values.closed_by.account_id,values.merge_commit.hash,"
    "values.participants.role,values.participants.approved,values.participants.user.account_id"
)
COMMENT_PARAMS = {
    "pagelen": 100,
    "fields": (
        "next,values.id,values.user.account_id,values.created_on,values.deleted,values.inline,"
        "values.parent.id,values.resolution"
    ),
}


class BitbucketConnector:
    name = SOURCE

    def __init__(
        self,
        client: BitbucketClient,
        db_path: Path,
        *,
        workspace: str = "",
        window_days: int = 90,
        now: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._client = client
        self._db_path = db_path
        self._workspace = workspace
        self._window_days = window_days
        self._now = now
        self._remaining = 0

    # --- selection -------------------------------------------------------------------------

    def _selected(self) -> List[Dict[str, str]]:
        conn = connect(self._db_path)
        try:
            return list_selected(conn, SOURCE)
        except sqlite3.OperationalError:
            return []  # database not migrated yet
        finally:
            conn.close()

    def _cursors(self) -> Dict[str, Optional[str]]:
        conn = connect(self._db_path)
        try:
            rows = conn.execute("SELECT scope, cursor FROM sync_state WHERE connector = ?", (SOURCE,)).fetchall()
            return {row["scope"]: row["cursor"] for row in rows}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def scopes(self) -> List[str]:
        """Selected repositories, unfinished ones (no saved cursor) first, then the oldest cursor first.

        One request budget is shared by the run, and a repository's list stage must finish to save its cursor.
        Going first, an unfinished repository gets the budget before another repository's detail backlog can use
        it up, so it is not listed again from the start on every run."""
        cursors = self._cursors()
        scopes = sorted((row["repository_id"] for row in self._selected()),
                        key=lambda uuid: (cursors.get(uuid) is not None, cursors.get(uuid) or "", uuid))
        self._remaining = len(scopes)
        return scopes

    def _selection_for(self, scope: str) -> Dict[str, str]:
        for row in self._selected():
            if row["repository_id"] == scope:
                return row
        raise BitbucketError(
            f"Repository {scope} is not selected. Run: delivery-analysis repos add bitbucket:<repo>"
        )

    # --- validation ------------------------------------------------------------------------

    def validate(self) -> List[str]:
        selected = self._selected()
        workspace = selected[0]["workspace"] if selected else self._workspace
        if not workspace:
            return []
        try:
            self._client.get(f"/repositories/{workspace}", {"pagelen": 1, "fields": "size"})
        except AuthError as exc:
            return [str(exc)]
        except ForbiddenError:
            return [
                "The token is missing the read:repository:bitbucket permission, or is limited to "
                "another workspace."
            ]
        except NotFoundError:
            return [f"Workspace {workspace!r} was not found or is not visible to this token."]
        except BitbucketError as exc:
            return [str(exc)]
        if selected:
            first = quote(selected[0]["repository_id"], safe="")
            try:
                self._client.get(
                    f"/repositories/{workspace}/{first}/pullrequests", {"pagelen": 1, "fields": "size"}
                )
            except ForbiddenError:
                return ["The token is missing the read:pullrequest:bitbucket permission."]
            except NotFoundError:
                pass  # that repository is judged when it is synced, not for every repository
            except BitbucketError as exc:
                return [str(exc)]
        return []

    # --- sync ------------------------------------------------------------------------------

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
        selection = self._selection_for(scope)
        self._remaining = max(0, self._remaining - 1)
        try:
            yield from self._sync_selected(scope, selection["workspace"], since)
        except BudgetExhausted:
            return  # the run budget is used up; the next sync continues

    def _sync_selected(self, scope: str, workspace: str, since: Optional[str]) -> Iterator[Batch]:
        repo_path = f"/repositories/{workspace}/{quote(scope, safe='')}"
        started = self._now()
        window = window_start(started, self._window_days)
        cutoff = since or window

        data = self._client.get(repo_path, {"fields": "uuid,slug,full_name,mainbranch.name"})
        record, raw = normalize.repository_record(workspace, data)
        yield Batch([record], [raw])

        yield from self._commits(scope, repo_path, cutoff, window)
        exact = self._exact_time_ids(scope)
        yield from self._pull_requests(scope, repo_path, cutoff, exact)
        yield Batch([], cursor=started)
        yield from self._detail(scope, repo_path)

    def _commits(self, uuid: str, repo_path: str, cutoff: str, window: str) -> Iterator[Batch]:
        params = {"pagelen": 100, "fields": COMMIT_FIELDS}
        for page in self._client.pages(f"{repo_path}/commits", params):
            values = page.get("values", [])
            records: List[Record] = []
            raws: List[RawPayload] = []
            all_old = bool(values)
            for item in values:
                committed = to_utc_iso(item.get("date"))
                if committed is None or committed >= cutoff:
                    all_old = False
                if committed is None or committed < window:
                    continue  # kept commits use the full window: author dates can be older than the cursor
                recs, raw = normalize.commit_records(uuid, item)
                records.extend(recs)
                raws.append(raw)
            if records:
                yield Batch(records, raws)
            if all_old:
                break

    def _pull_requests(
        self, uuid: str, repo_path: str, cutoff: str, exact: Set[str]
    ) -> Iterator[Batch]:
        params: Dict[str, Any] = {
            "state": PR_STATES, "sort": "-updated_on", "pagelen": PR_PAGELEN, "fields": PR_FIELDS,
        }
        for page in self._client.pages(f"{repo_path}/pullrequests", params):
            records: List[Record] = []
            raws: List[RawPayload] = []
            stop = False
            for item in page.get("values", []):
                updated = to_utc_iso(item.get("updated_on"))
                if updated is not None and updated < cutoff:
                    stop = True
                    break
                source_id = f"{uuid}#{item['id']}"
                recs, raw = normalize.pull_request_records(
                    uuid, item, include_times=source_id not in exact
                )
                records.extend(recs)
                raws.append(raw)
            if records:
                yield Batch(records, raws)
            if stop:
                break

    def _exact_time_ids(self, uuid: str) -> Set[str]:
        """Pull requests whose merge/close times came from activity and must not be approximated."""
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT record_id FROM property WHERE record_kind = 'change_request' "
                "AND name = 'times_from' AND value = 'activity' AND record_id LIKE ?",
                (uuid + "#%",),
            ).fetchall()
            return {row["record_id"] for row in rows}
        finally:
            conn.close()

    def _pending_detail(self, uuid: str) -> List[Dict[str, str]]:
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT u.record_id AS source_id, u.value AS updated FROM property u "
                "LEFT JOIN property d ON d.record_kind = 'change_request' AND d.record_id = u.record_id "
                "AND d.name = 'detail_updated_on' "
                "WHERE u.record_kind = 'change_request' AND u.name = 'updated_on' AND u.record_id LIKE ? "
                "AND (d.value IS NULL OR d.value != u.value) ORDER BY u.value DESC",
                (uuid + "#%",),
            ).fetchall()
            return [{"source_id": r["source_id"], "updated": r["updated"]} for r in rows]
        finally:
            conn.close()

    def _pending_comments(self, uuid: str) -> List[Dict[str, str]]:
        """Pull requests detailed before comments were fetched (or changed since), newest first."""
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT d.record_id AS source_id, d.value AS detailed FROM property d "
                "LEFT JOIN property c ON c.record_kind = 'change_request' AND c.record_id = d.record_id "
                "AND c.name = 'comments_detail_on' "
                "WHERE d.record_kind = 'change_request' AND d.name = 'detail_updated_on' AND d.record_id LIKE ? "
                "AND (c.value IS NULL OR c.value != d.value) ORDER BY d.value DESC",
                (uuid + "#%",),
            ).fetchall()
            return [{"source_id": r["source_id"], "detailed": r["detailed"]} for r in rows]
        finally:
            conn.close()

    def _backfill_comments(self, uuid: str, repo_path: str) -> Iterator[Batch]:
        """Fetch only the comments of pull requests that were detailed without them."""
        for pending in self._pending_comments(uuid):
            if self._client.budget_left < self._remaining * RESERVE_PER_REPO + 1:
                return
            source_id, detailed = pending["source_id"], pending["detailed"]
            number = source_id.split("#", 1)[1]
            try:
                comments = self._optional_items(f"{repo_path}/pullrequests/{number}/comments", COMMENT_PARAMS)
            except (BudgetExhausted, RateLimitedError):
                return
            except AuthError:
                raise
            except BitbucketError:
                continue  # retried on the next sync
            records = normalize.review_comment_records(source_id, comments)
            records.append(normalize.prop("change_request", source_id, "comments_detail_on", detailed))
            yield Batch(records, replace=[("review_comment", {"change_request_id": source_id})])

    def _commits_to_link(self, source_id: str, commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The commits this pull request may own. A commit belongs to one pull request, so a commit stays
        with a merged pull request over an unmerged one, then with the one that has fewer commits; a tie
        keeps the current owner. Without this, a release pull request or one built from the wrong branch
        takes every feature pull request's commits and their code weighting."""
        if not commits:
            return commits
        conn = connect(self._db_path)
        try:
            row = conn.execute("SELECT state FROM change_request WHERE source_id = ?", (source_id,)).fetchone()
            mine = (0 if row is not None and row["state"] == "MERGED" else 1, len(commits))
            owners: Dict[str, tuple] = {}
            hashes = [c["hash"] for c in commits]
            for start in range(0, len(hashes), 500):
                chunk = hashes[start:start + 500]
                for r in conn.execute(
                    "SELECT v.sha, v.change_request_id, cr.state, cr.commit_count FROM vcs_commit v "
                    "JOIN change_request cr ON cr.source_id = v.change_request_id "
                    "WHERE v.change_request_id IS NOT NULL AND v.change_request_id != ? AND v.sha IN (%s)"
                    % ",".join("?" for _ in chunk),
                    [source_id, *chunk],
                ):
                    count = r["commit_count"] if r["commit_count"] else float("inf")
                    owners[r["sha"]] = (0 if r["state"] == "MERGED" else 1, count)
        finally:
            conn.close()
        return [c for c in commits if c["hash"] not in owners or mine < owners[c["hash"]]]

    def _all_items(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for page in self._client.pages(path, params):
            items.extend(page.get("values", []))
        return items

    def _optional_items(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """A pull request's commits or diffstat can be gone (deleted branch); that is empty, not an error."""
        try:
            return self._all_items(path, params)
        except NotFoundError:
            return []

    def _detail(self, uuid: str, repo_path: str) -> Iterator[Batch]:
        succeeded = 0
        last_error: Optional[BitbucketError] = None
        for pending in self._pending_detail(uuid):
            if self._client.budget_left < self._remaining * RESERVE_PER_REPO + 4:
                return
            source_id, updated = pending["source_id"], pending["updated"]
            number = source_id.split("#", 1)[1]
            base = f"{repo_path}/pullrequests/{number}"
            try:
                activity = self._all_items(f"{base}/activity", {"pagelen": PR_PAGELEN})
                commits = self._optional_items(f"{base}/commits", {"pagelen": 100, "fields": "next,values.hash"})
                diffstat = self._optional_items(f"{base}/diffstat", {"pagelen": 100})
                comments = self._optional_items(f"{base}/comments", COMMENT_PARAMS)
            except (BudgetExhausted, RateLimitedError):
                return
            except NotFoundError:
                yield Batch([normalize.prop("change_request", source_id, "detail_updated_on", updated)])
                continue
            except AuthError:
                raise
            except BitbucketError as exc:
                last_error = exc  # this pull request is retried on the next sync
                continue
            events, summary = normalize.activity_records(source_id, activity)
            values: Dict[str, Any] = {
                "source": SOURCE,
                "source_id": source_id,
                "files_changed": len(diffstat),
                "commit_count": len(commits),
            }
            if summary.merged_at is not None:
                values["merged_at"] = summary.merged_at
            if summary.closed_at is not None:
                values["closed_at"] = summary.closed_at
            records: List[Record] = list(events)
            records.append(Record("change_request", values))
            records.extend(normalize.commit_link_records(uuid, source_id, self._commits_to_link(source_id, commits)))
            records.extend(normalize.review_comment_records(source_id, comments))
            if summary.closed_at is not None:
                records.append(normalize.prop("change_request", source_id, "times_from", "activity"))
            records.append(normalize.prop("change_request", source_id, "detail_updated_on", updated))
            records.append(normalize.prop("change_request", source_id, "comments_detail_on", updated))
            raw = RawPayload(SOURCE, source_id, "pr_activity", json.dumps(activity, sort_keys=True))
            succeeded += 1
            yield Batch(records, [raw], replace=[("review_comment", {"change_request_id": source_id})])
        yield from self._backfill_comments(uuid, repo_path)
        if last_error is not None and succeeded == 0:
            raise last_error  # every pull request failed the same way: that is a real problem, not a skip
