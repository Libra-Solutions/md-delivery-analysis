from metrics_seed import REPO, SEPT, TODAY, TZ, event, pr, put, seed
from delivery_analysis.metrics import review_quality as rq
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
ANN = "bitbucket:acc-ann"
BOB = "bitbucket:acc-bob"


def comment(conn, cid, pr_n, actor, when="2026-09-03T12:00:00Z", path=None, parent=None):
    sid = f"{REPO}#{pr_n}"
    put(
        conn, "review_comment", source="bitbucket", source_id=f"{sid}:comment:{cid}", change_request_id=sid,
        actor_account=actor, created_at=when, path=path, line=3 if path else None,
        parent_id=f"{sid}:comment:{parent}" if parent else None, resolved=0,
    )


def test_comments_received(conn):
    seed(conn)
    comment(conn, 1, 1, "acc-bob")
    comment(conn, 2, 1, "acc-zed")
    comment(conn, 3, 3, "acc-bob")
    obs = rq.comments_received_per_pr(conn, Scope(), WINDOW)
    # Ann merged PRs 1, 2, 3 (and 6 in another repo, counted without a team)
    assert sorted(obs.pairs[ANN]) == [(0.0, 1.0, 1), (0.0, 1.0, 1), (1.0, 1.0, 1), (2.0, 1.0, 1)]


def test_self_comments_ignored(conn):
    seed(conn)
    comment(conn, 1, 1, "acc-ann", path="a.cs")
    obs = rq.comments_received_per_pr(conn, Scope(), WINDOW)
    assert all(num == 0.0 for num, _, _ in obs.pairs[ANN])
    assert rq.inline_comments_given(conn, Scope(), WINDOW).by_actor == {}


def test_replies_ignored(conn):
    seed(conn)
    comment(conn, 1, 1, "acc-bob")
    comment(conn, 2, 1, "acc-zed", parent=1)
    obs = rq.comments_received_per_pr(conn, Scope(), WINDOW)
    assert sorted(obs.pairs[ANN])[-1] == (1.0, 1.0, 1)


def test_inline_given(conn):
    seed(conn)
    comment(conn, 1, 1, "acc-bob", path="a.cs")
    comment(conn, 2, 1, "acc-bob", path="b.cs")
    comment(conn, 3, 1, "acc-bob")
    comment(conn, 4, 1, "acc-bob", when="2026-10-03T12:00:00Z", path="c.cs")
    assert rq.inline_comments_given(conn, Scope(), WINDOW).by_actor == {BOB: [1.0, 1.0]}


def test_teammates_distinct(conn):
    seed(conn)
    pr(conn, 8, "acc-cy", "MERGED", "2026-09-05T14:00:00Z", "2026-09-06T14:00:00Z")
    event(conn, f"{REPO}#1", "comment", "acc-bob", "2026-09-03T12:00:00Z")
    event(conn, f"{REPO}#2", "approved", "acc-bob", "2026-09-11T12:00:00Z")
    event(conn, f"{REPO}#8", "comment", "acc-bob", "2026-09-06T12:00:00Z")
    assert rq.teammates_reviewed(conn, Scope(), WINDOW).by_actor[BOB] == [2.0]


def test_empty_window(conn):
    assert rq.teammates_reviewed(conn, Scope(), WINDOW).by_actor == {}
    assert rq.comments_received_per_pr(conn, Scope(), WINDOW).pairs == {}
