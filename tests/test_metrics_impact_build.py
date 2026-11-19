import json

import pytest

from impact_seed import issue, link_pr
from metrics_seed import NOW, OTHER, REPO, pr, put
from delivery_analysis.metrics.credit import actor_for
from delivery_analysis.metrics.impact_build import ImpactSummary, rebuild_impact

ANN = actor_for("acc-ann")
BOB = actor_for("acc-bob")
CY = actor_for("acc-cy")
DONE = "2026-09-10T12:00:00Z"
COMMENT_AT = "2026-09-08T12:00:00Z"
FIX_AT = "2026-09-08T14:00:00Z"
MERGED = "2026-09-09T12:00:00Z"


def code(conn, repo, path, weight):
    put(conn, "code_file", repository_id=repo, path=path, weight=weight, snapshot_sha="s", built_at=NOW)


def work(conn, pr_sid, sha, account, when, files, repo=REPO):
    """A commit on a pull request touching {path: [[start, end], ...]}."""
    put(conn, "vcs_commit", source="bitbucket", source_id=f"{repo}:{sha}", repository_id=repo, sha=sha,
        author_account=account, committed_at=when, change_request_id=pr_sid)
    for path, hunks in files.items():
        put(conn, "commit_file", repository_id=repo, sha=sha, path=path, lines_added=1, lines_removed=0,
            hunks=json.dumps(hunks))


def comment(conn, pr_sid, cid, actor, when=COMMENT_AT, path=None, line=None, parent=None, resolved=0):
    put(conn, "review_comment", source="bitbucket", source_id=f"{pr_sid}:comment:{cid}", change_request_id=pr_sid,
        actor_account=actor, created_at=when, path=path, line=line,
        parent_id=f"{pr_sid}:comment:{parent}" if parent else None, resolved=resolved)


def baseline(conn, count, weight=3.7):
    """`count` earlier one-point tickets in another repository, each of scope `weight`."""
    code(conn, OTHER, "x.py", weight)
    for i in range(1, count + 1):
        issue(conn, f"b{i}", "acc-bob", resolved=f"2026-08-0{i}T12:00:00Z", started="2026-07-30T12:00:00Z", points=1)
        sid = pr(conn, 900 + i, "acc-bob", "MERGED", "2026-07-31T12:00:00Z", f"2026-08-0{i}T10:00:00Z", repo=OTHER)
        link_pr(conn, 900 + i, f"b{i}", repo=OTHER)
        work(conn, sid, f"bs{i}", "acc-bob", "2026-08-01T08:00:00Z", {"x.py": [[1, 2]]}, repo=OTHER)


def ticket(conn, points=5, number=100, assignee="acc-ann", author="acc-ann", merged=MERGED, sid="T"):
    issue(conn, sid, assignee, resolved=DONE, started="2026-09-07T12:00:00Z", points=points)
    pr_sid = pr(conn, number, author, "MERGED", "2026-09-07T09:00:00Z", merged)
    link_pr(conn, number, sid)
    return pr_sid


def shares(conn):
    return {
        (row["issue_id"], row["actor_key"]): dict(row)
        for row in conn.execute("SELECT * FROM impact_share")
    }


def fixes(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM comment_fix ORDER BY comment_id")]


def simple_fix(conn, *, line=50, hunk=(60, 62), **extra):
    """A 5-point ticket (F = 1, every file r = 1): inline comment on src/a.py, later commit changes it."""
    code(conn, REPO, "src/a.py", 1.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"src/a.py": [[1, 2]]})
    comment(conn, sid, 1, "acc-bob", path="src/a.py", line=line)
    work(conn, sid, "c2", "acc-ann", FIX_AT, {"src/a.py": [list(hunk)]})
    return sid


def test_the_worked_example(conn):
    """5 points, one core file (w 7.4), median ticket scope 3.7: F = 2, V = 10; one fix with r = 3."""
    baseline(conn, 5)
    code(conn, REPO, "src/core.py", 7.4)
    code(conn, REPO, "src/mid.py", 7.4 / 3)
    code(conn, REPO, "src/leaf.py", 1.0)  # median weight of the repository's code files is 7.4 / 3
    sid = ticket(conn, points=5)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"src/core.py": [[10, 20]]})
    comment(conn, sid, 1, "acc-bob", path="src/core.py", line=42)
    work(conn, sid, "c2", "acc-ann", FIX_AT, {"src/core.py": [[40, 44]]})
    summary = rebuild_impact(conn, NOW)
    row = conn.execute("SELECT * FROM pr_value WHERE pr_id = ?", (sid,)).fetchone()
    assert row["issue_id"] == "T" and row["has_files"] == 1
    assert row["scope"] == pytest.approx(7.4) and row["value"] == pytest.approx(10.0)
    (fix,) = fixes(conn)
    assert fix["rel_weight"] == pytest.approx(3.0) and fix["fix_sha"] == "c2" and fix["path"] == "src/core.py"
    assert fix["reviewer_credit"] == pytest.approx(1.5) and fix["owner_penalty"] == pytest.approx(0.15)
    assert fix["reviewer_key"] == BOB and fix["owner_key"] == ANN
    out = shares(conn)
    assert out[("T", ANN)]["delivery"] == pytest.approx(9.85)
    assert out[("T", ANN)]["penalty"] == pytest.approx(0.15)
    assert out[("T", ANN)]["scope_factor"] == pytest.approx(2.0) and out[("T", ANN)]["value"] == pytest.approx(10.0)
    assert out[("T", BOB)]["participation"] == pytest.approx(1.5) and out[("T", BOB)]["delivery"] == 0.0
    assert out[("T", ANN)]["resolved_at"] == DONE
    assert isinstance(summary, ImpactSummary) and summary.fixes == 1 and summary.tickets == 6


def test_no_file_data_for_any_pr_falls_back_to_the_assignee(conn):
    ticket(conn, points=5, assignee="acc-cy", author="acc-bob")
    issue(conn, "U", "acc-ann", resolved=DONE, points=3)  # no pull request at all
    summary = rebuild_impact(conn, NOW)
    out = shares(conn)
    assert out[("T", CY)] == {**out[("T", CY)], "delivery": 5.0, "participation": 0.0, "penalty": 0.0,
                              "scope_factor": 1.0, "value": 5.0}
    assert ("T", BOB) not in out and out[("U", ANN)]["delivery"] == 3.0
    assert summary.prs_without_files == 1 and summary.tickets == 2


def test_a_pr_without_files_gets_the_mean_scope_of_its_siblings(conn):
    code(conn, REPO, "a.py", 2.0)
    code(conn, REPO, "b.py", 4.0)
    issue(conn, "T", "acc-cy", resolved=DONE, started="2026-09-07T12:00:00Z", points=6)
    a = pr(conn, 1, "acc-ann", "MERGED", "2026-09-07T09:00:00Z", MERGED)
    b = pr(conn, 2, "acc-bob", "MERGED", "2026-09-07T09:00:00Z", MERGED)
    c = pr(conn, 3, "acc-cy", "MERGED", "2026-09-07T09:00:00Z", MERGED)
    for number in (1, 2, 3):
        link_pr(conn, number, "T")
    work(conn, a, "ca", "acc-ann", "2026-09-08T09:00:00Z", {"a.py": [[1, 1]]})
    work(conn, b, "cb", "acc-bob", "2026-09-08T09:00:00Z", {"b.py": [[1, 1]]})
    summary = rebuild_impact(conn, NOW)
    values = {row["pr_id"]: dict(row) for row in conn.execute("SELECT * FROM pr_value")}
    assert values[c]["scope"] == pytest.approx(3.0) and values[c]["has_files"] == 0
    assert values[a]["value"] == pytest.approx(6 * 2 / 9) and values[b]["value"] == pytest.approx(6 * 4 / 9)
    assert values[c]["value"] == pytest.approx(6 * 3 / 9)
    out = shares(conn)
    assert out[("T", CY)]["delivery"] == pytest.approx(2.0) and out[("T", CY)]["scope_factor"] == 1.0
    assert summary.prs_valued == 3 and summary.prs_without_files == 1


@pytest.mark.parametrize("count, factor", [(4, 1.0), (5, 2.0)])
def test_fewer_than_five_baseline_tickets_gives_a_factor_of_one(conn, count, factor):
    baseline(conn, count, weight=3.0)
    code(conn, REPO, "big.py", 6.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"big.py": [[1, 2]]})
    rebuild_impact(conn, NOW)
    assert shares(conn)[("T", ANN)]["scope_factor"] == pytest.approx(factor)
    assert shares(conn)[("T", ANN)]["value"] == pytest.approx(5 * factor)


def test_baseline_only_looks_back_90_days(conn):
    baseline(conn, 5, weight=3.0)
    conn.execute("UPDATE work_item SET resolved_at = '2026-05-01T12:00:00Z' WHERE source_id IN ('b1', 'b2')")
    code(conn, REPO, "big.py", 6.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"big.py": [[1, 2]]})
    rebuild_impact(conn, NOW)
    assert shares(conn)[("T", ANN)]["scope_factor"] == 1.0  # only 3 tickets inside the 90 days


@pytest.mark.parametrize("line, hunk, fixed", [
    (50, (60, 62), True),   # hunk starts 10 lines after the comment
    (50, (61, 62), False),  # 11 lines after
    (50, (30, 40), True),   # hunk ends 10 lines before
    (50, (30, 39), False),  # 11 lines before
    (50, (45, 55), True),   # the comment sits inside the hunk
])
def test_an_inline_fix_must_touch_within_ten_lines(conn, line, hunk, fixed):
    simple_fix(conn, line=line, hunk=hunk)
    rebuild_impact(conn, NOW)
    assert len(fixes(conn)) == (1 if fixed else 0)


def test_an_inline_comment_without_a_line_is_fixed_by_any_change_to_the_file(conn):
    simple_fix(conn, line=None, hunk=(900, 905))
    rebuild_impact(conn, NOW)
    (fix,) = fixes(conn)
    assert fix["fix_sha"] == "c2" and fix["reviewer_credit"] == pytest.approx(0.25)
    assert fix["owner_penalty"] == pytest.approx(0.025)


def test_a_change_to_another_file_does_not_fix_an_inline_comment(conn):
    code(conn, REPO, "src/a.py", 1.0)
    code(conn, REPO, "src/b.py", 1.0)
    sid = ticket(conn)
    comment(conn, sid, 1, "acc-bob", path="src/a.py", line=None)
    work(conn, sid, "c2", "acc-ann", FIX_AT, {"src/b.py": [[1, 2]]})
    rebuild_impact(conn, NOW)
    assert fixes(conn) == []


def test_a_non_inline_resolved_comment_uses_the_mean_relative_weight(conn):
    code(conn, REPO, "core.py", 7.4)
    code(conn, REPO, "mid.py", 7.4 / 3)
    code(conn, REPO, "leaf.py", 1.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"core.py": [[1, 2]], "leaf.py": [[1, 2]]})
    comment(conn, sid, 1, "acc-bob", resolved=1)
    comment(conn, sid, 2, "acc-bob", resolved=0)  # not resolved: no credit
    work(conn, sid, "c2", "acc-ann", FIX_AT, {"leaf.py": [[9, 9]]})
    rebuild_impact(conn, NOW)
    (fix,) = fixes(conn)
    mean_r = (3.0 + 1.0 / (7.4 / 3)) / 2
    assert fix["comment_id"].endswith(":comment:1") and fix["path"] is None
    assert fix["rel_weight"] == pytest.approx(mean_r)


def test_a_resolved_non_inline_comment_needs_a_later_commit(conn):
    code(conn, REPO, "a.py", 1.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"a.py": [[1, 2]]})
    comment(conn, sid, 1, "acc-bob", resolved=1)
    rebuild_impact(conn, NOW)
    assert fixes(conn) == []


@pytest.mark.parametrize("replier, fixed", [("acc-ann", True), ("acc-cy", False)])
def test_a_non_inline_comment_the_owner_replied_to_is_fixed_by_a_later_commit(conn, replier, fixed):
    code(conn, REPO, "a.py", 1.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"a.py": [[1, 2]]})
    comment(conn, sid, 1, "acc-bob")  # general, never marked resolved
    comment(conn, sid, 2, replier, when="2026-09-08T13:00:00Z", parent=1)
    work(conn, sid, "c2", "acc-ann", FIX_AT, {"a.py": [[9, 9]]})
    rebuild_impact(conn, NOW)
    assert [f["fix_sha"] for f in fixes(conn)] == (["c2"] if fixed else [])


def test_an_owner_reply_without_a_later_commit_is_not_a_fix(conn):
    code(conn, REPO, "a.py", 1.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"a.py": [[1, 2]]})
    comment(conn, sid, 1, "acc-bob")
    comment(conn, sid, 2, "acc-ann", when="2026-09-08T13:00:00Z", parent=1)
    rebuild_impact(conn, NOW)
    assert fixes(conn) == []


def test_replies_never_count(conn):
    simple_fix(conn)
    comment(conn, f"{REPO}#100", 2, "acc-bob", path="src/a.py", line=50, parent=1)
    rebuild_impact(conn, NOW)
    assert [f["comment_id"] for f in fixes(conn)] == [f"{REPO}#100:comment:1"]


def test_comments_by_the_pr_owner_are_ignored(conn):
    simple_fix(conn)
    conn.execute("UPDATE review_comment SET actor_account = 'acc-ann'")
    rebuild_impact(conn, NOW)
    assert fixes(conn) == []


def test_commits_before_the_comment_or_after_the_merge_do_not_fix(conn):
    code(conn, REPO, "src/a.py", 1.0)
    sid = ticket(conn)
    work(conn, sid, "early", "acc-ann", "2026-09-08T09:00:00Z", {"src/a.py": [[50, 50]]})
    comment(conn, sid, 1, "acc-bob", path="src/a.py", line=50)
    work(conn, sid, "late", "acc-ann", "2026-09-09T13:00:00Z", {"src/a.py": [[50, 50]]})
    rebuild_impact(conn, NOW)
    assert fixes(conn) == []
    work(conn, sid, "mid", "acc-cy", FIX_AT, {"src/a.py": [[50, 50]]})
    rebuild_impact(conn, NOW)
    (fix,) = fixes(conn)
    assert fix["fix_sha"] == "mid" and fix["owner_key"] == ANN  # the owner pays whoever wrote the fix


def test_the_penalty_floors_delivery_at_zero_and_the_reviewer_credit_is_capped(conn):
    code(conn, REPO, "src/a.py", 1.0)
    sid = ticket(conn)  # V = 5, every fix 0.25 credit and 0.025 penalty
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"src/a.py": [[1, 2]]})
    for i in range(1, 251):
        comment(conn, sid, i, "acc-bob", path="src/a.py", line=None)
    work(conn, sid, "c2", "acc-ann", FIX_AT, {"src/a.py": [[1, 2]]})
    summary = rebuild_impact(conn, NOW)
    out = shares(conn)
    assert summary.fixes == 250
    assert out[("T", ANN)]["delivery"] == 0.0 and out[("T", ANN)]["penalty"] == pytest.approx(250 * 0.025)
    assert out[("T", BOB)]["participation"] == pytest.approx(5.0)  # capped at V(p)


def test_a_missing_commit_does_not_stop_the_pr_falling_back(conn):
    code(conn, REPO, "src/a.py", 1.0)
    sid = ticket(conn)
    comment(conn, sid, 1, "acc-bob", path="src/a.py", line=3)
    rebuild_impact(conn, NOW)
    assert fixes(conn) == [] and shares(conn)[("T", ANN)]["delivery"] == 5.0


def tables(conn):
    return {
        name: [tuple(row) for row in conn.execute(f"SELECT * FROM {name} ORDER BY 1, 2")]
        for name in ("pr_value", "comment_fix", "impact_share")
    }


def test_rebuild_is_idempotent_and_replaces_stale_rows(conn):
    baseline(conn, 5)
    simple_fix(conn)
    first = rebuild_impact(conn, NOW)
    before = tables(conn)
    assert before["impact_share"] and before["pr_value"]
    assert rebuild_impact(conn, NOW) == first
    assert tables(conn) == before
    conn.execute("DELETE FROM review_comment")
    conn.execute("DELETE FROM link WHERE to_id = 'T'")
    rebuild_impact(conn, NOW)
    after = tables(conn)
    assert after["comment_fix"] == [] and not any(row[1] == "T" for row in after["pr_value"])
    assert [row[3] for row in after["impact_share"] if row[0] == "T"] == [5.0]  # back to the assignee


def test_an_unlinked_pr_gets_no_value_and_a_pr_for_two_tickets_counts_once(conn):
    code(conn, REPO, "a.py", 1.0)
    sid = ticket(conn)
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"a.py": [[1, 2]]})
    pr(conn, 7, "acc-bob", "MERGED", "2026-09-01T09:00:00Z", "2026-09-02T09:00:00Z")  # not linked
    issue(conn, "V", "acc-bob", resolved="2026-09-11T12:00:00Z", points=4)
    link_pr(conn, 100, "V")
    rebuild_impact(conn, NOW)
    values = [dict(row) for row in conn.execute("SELECT pr_id, issue_id FROM pr_value")]
    assert values == [{"pr_id": sid, "issue_id": "T"}]
    assert shares(conn)[("V", actor_for("acc-bob"))]["delivery"] == 4.0  # V fell back to its assignee


def test_the_summary_lines_name_every_count():
    summary = ImpactSummary(tickets=4, prs_valued=3, prs_without_files=1, fixes=2)
    text = " ".join(summary.lines())
    for number in ("4", "3", "1", "2"):
        assert number in text
    assert len(summary.lines()) >= 2


def _open_pr_fix(conn, commit_at):
    code(conn, REPO, "src/a.py", 1.0)
    issue(conn, "T", "acc-ann", resolved=DONE, started="2026-09-07T12:00:00Z", points=5)
    sid = pr(conn, 100, "acc-ann", "OPEN", "2026-09-07T09:00:00Z")
    link_pr(conn, 100, "T")
    work(conn, sid, "c1", "acc-ann", "2026-09-08T09:00:00Z", {"src/a.py": [[1, 2]]})
    comment(conn, sid, 1, "acc-bob", path="src/a.py", line=50)
    work(conn, sid, "c2", "acc-ann", commit_at, {"src/a.py": [[50, 50]]})


def test_an_open_pr_is_only_fixed_before_the_ticket_was_delivered(conn):
    _open_pr_fix(conn, "2026-09-11T09:00:00Z")  # after DONE
    rebuild_impact(conn, NOW)
    assert fixes(conn) == []


def test_an_open_pr_commit_before_the_delivered_date_fixes(conn):
    _open_pr_fix(conn, "2026-09-09T09:00:00Z")  # before DONE
    rebuild_impact(conn, NOW)
    (fix,) = fixes(conn)
    assert fix["fix_sha"] == "c2"
