import pytest

from impact_seed import seed_impact
from metrics_seed import SEPT, TODAY, TZ, prop
from delivery_analysis.metrics import credit as cr
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)


def key(account):
    return f"jira:{account}|bitbucket:{account}"


def qa(conn, issue_id, qa1=None, qa2=None, slugs=("qa1_10200", "qa2_10201")):
    if qa1 is not None:
        prop(conn, "work_item", issue_id, slugs[0], qa1)
    if qa2 is not None:
        prop(conn, "work_item", issue_id, slugs[1], qa2)


def rows(conn, name):
    return {r["name"]: r["value"] for r in run_metric(conn, BY_NAME[name], Scope(), WINDOW)["rows"]}


def test_two_different_testers_split_the_ticket_in_half(conn):
    seed_impact(conn)
    qa(conn, "1", "acc-ann", "acc-bob")
    assert cr.qa_shares(conn, ["1"]) == {"1": {key("acc-ann"): 0.5, key("acc-bob"): 0.5}}


def test_the_same_tester_twice_and_an_empty_field_count_once(conn):
    seed_impact(conn)
    qa(conn, "1", "acc-bob", "acc-bob")
    qa(conn, "3", "", "acc-bob")
    assert cr.qa_shares(conn, ["1", "3"]) == {"1": {key("acc-bob"): 1.0}, "3": {key("acc-bob"): 1.0}}


def test_fields_named_with_a_space_are_read_too(conn):
    seed_impact(conn)
    qa(conn, "1", "acc-ann", "acc-bob", slugs=("qa_1_10300", "qa_2_10301"))
    assert cr.qa_shares(conn, ["1"]) == {"1": {key("acc-ann"): 0.5, key("acc-bob"): 0.5}}


def test_qa_points_go_to_the_testers_and_leave_story_points_done_unchanged(conn):
    seed_impact(conn)
    before = rows(conn, "story_points_done")
    qa(conn, "1", "acc-bob")  # 5 points, delivered in September, credited to Ann as a developer
    qa(conn, "8", "acc-bob")  # August: outside the window
    assert rows(conn, "qa_points_done")["Bob Builder"] == pytest.approx(5.0)
    assert "Ann Example" not in rows(conn, "qa_points_done")
    assert rows(conn, "story_points_done") == before


def test_qa_points_explain_how_many_tickets_have_no_tester(conn):
    seed_impact(conn)
    qa(conn, "1", "acc-bob")
    notes = run_metric(conn, BY_NAME["qa_points_done"], Scope(), WINDOW)["notes"]
    assert any("no QA1 or QA2" in note for note in notes)
