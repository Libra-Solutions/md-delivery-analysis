from impact_seed import issue, link_pr, seed_impact
from metrics_seed import SEPT, TODAY, TZ, pr, prop
from delivery_analysis.metrics import ticket_shape as ts
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
OCT = make_window("month:2026-10", TZ, TODAY)
ANN = "jira:acc-ann|bitbucket:acc-ann"
BOB = "jira:acc-bob|bitbucket:acc-bob"


def test_big_ticket_threshold(conn):
    seed_impact(conn)
    issue(conn, "20", "acc-ann", resolved="2026-09-13T14:00:00Z", points=8)
    issue(conn, "21", "acc-ann", resolved="2026-09-13T14:00:00Z", points=5)
    issue(conn, "22", "acc-ann", resolved="2026-09-13T14:00:00Z", points=13)
    assert ts.big_tickets(conn, Scope(), WINDOW).by_actor[ANN] == [1.0, 1.0]


def test_dev1_gets_three_quarters_and_dev2_a_quarter(conn):
    seed_impact(conn)
    issue(conn, "20", "acc-ann", resolved="2026-09-13T14:00:00Z", points=13)
    prop(conn, "work_item", "20", "dev1_10100", "acc-ann")
    prop(conn, "work_item", "20", "dev2_10101", "acc-bob")
    obs = ts.big_tickets(conn, Scope(), WINDOW)
    assert obs.by_actor[ANN] == [0.75]
    assert obs.by_actor[BOB] == [0.25]


def test_points_by_merge_date(conn):
    seed_impact(conn)
    pr(conn, 30, "acc-ann", "MERGED", "2026-10-05T14:00:00Z", "2026-10-10T14:00:00Z")
    issue(conn, "30", "acc-ann", resolved="2026-10-26T14:00:00Z", points=8)
    link_pr(conn, 30, "30")
    assert ts.points_by_merge_date(conn, Scope(), OCT).by_actor[ANN] == [8.0]
    assert 8.0 not in ts.points_by_merge_date(conn, Scope(), WINDOW).by_actor.get(ANN, [])


def test_merge_date_moves_ticket_across_months(conn):
    seed_impact(conn)
    pr(conn, 31, "acc-ann", "MERGED", "2026-09-25T14:00:00Z", "2026-09-28T14:00:00Z")
    issue(conn, "31", "acc-ann", resolved="2026-10-02T14:00:00Z", points=3)
    link_pr(conn, 31, "31")
    assert 3.0 in ts.points_by_merge_date(conn, Scope(), WINDOW).by_actor[ANN]
    assert ts.points_by_merge_date(conn, Scope(), OCT).by_actor == {}


def test_no_linked_pr_falls_back(conn):
    seed_impact(conn)
    issue(conn, "32", "acc-ann", resolved="2026-10-26T14:00:00Z", points=2.5)
    assert ts.points_by_merge_date(conn, Scope(), OCT).by_actor[ANN] == [2.5]
    assert 2.5 not in ts.points_by_merge_date(conn, Scope(), WINDOW).by_actor[ANN]


def test_empty(conn):
    assert ts.big_tickets(conn, Scope(), WINDOW).by_actor == {}
    assert ts.points_by_merge_date(conn, Scope(), WINDOW).by_actor == {}
