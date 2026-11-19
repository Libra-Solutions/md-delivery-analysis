import pytest

from impact_seed import issue, link_pr, seed_impact
from metrics_seed import SEPT, TODAY, TZ, pr, prop
from delivery_analysis.metrics import credit as cr
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)


def key(account):
    return f"jira:{account}|bitbucket:{account}"


def dev(conn, issue_id, dev1=None, dev2=None):
    if dev1 is not None:
        prop(conn, "work_item", issue_id, "dev1_10100", dev1)
    if dev2 is not None:
        prop(conn, "work_item", issue_id, "dev2_10101", dev2)


def test_dev1_gets_three_quarters_and_dev2_the_reviewer_a_quarter(conn):
    seed_impact(conn)
    dev(conn, "2", "acc-ann", "acc-bob")
    assert cr.dev_shares(conn, ["2"]) == {"2": {key("acc-ann"): 0.75, key("acc-bob"): 0.25}}
    credit = cr.credit_for(conn, WINDOW)
    assert credit.shares["2"] == {key("acc-ann"): 0.75, key("acc-bob"): 0.25}
    assert credit.by_dev == {"2"}


def test_equal_ids_are_credited_once_in_full(conn):
    seed_impact(conn)
    dev(conn, "2", "acc-bob", "acc-bob")
    assert cr.dev_shares(conn, ["2"]) == {"2": {key("acc-bob"): 1.0}}


def test_only_dev2_gets_the_whole_ticket(conn):
    seed_impact(conn)
    dev(conn, "2", None, "acc-bob")
    assert cr.credit_for(conn, WINDOW).shares["2"] == {key("acc-bob"): 1.0}
    dev(conn, "6", "", "acc-bob")  # an empty Dev1 counts as not set
    assert cr.dev_shares(conn, ["6"]) == {"6": {key("acc-bob"): 1.0}}


def test_dev_fields_win_over_pull_request_authors_and_the_assignee(conn):
    seed_impact(conn)
    dev(conn, "1", "acc-bob")  # issue 1 has a linked PR by Ann
    dev(conn, "3", "acc-ann", "acc-zed")  # issue 3 is linked to Ann and Bob
    credit = cr.credit_for(conn, WINDOW)
    assert credit.shares["1"] == {key("acc-bob"): 1.0}
    assert credit.shares["3"] == {key("acc-ann"): 0.75, key("acc-zed"): 0.25}
    assert credit.by_dev == {"1", "3"} and credit.by_pr == set()


def test_dev_fields_win_over_claude_era_evidence(conn):
    seed_impact(conn)
    conn.execute("INSERT INTO person (person_id, display_name, excluded, manual) VALUES ('p9', 'Pat', 0, 0)")
    conn.execute(
        "INSERT INTO ticket_credit (work_item_source, work_item_id, person_id, share, evidence, method) VALUES ('jira', '2', 'p9', 1.0, 1.0, 'x')"
    )
    assert cr.credit_for(conn, WINDOW).by_evidence == {"2"}
    dev(conn, "2", "acc-bob")
    credit = cr.credit_for(conn, WINDOW)
    assert credit.shares["2"] == {key("acc-bob"): 1.0} and credit.by_evidence == set()


def test_an_empty_dev1_and_dev2_fall_back_to_the_existing_order(conn):
    seed_impact(conn)
    dev(conn, "2", "", "  ")
    credit = cr.credit_for(conn, WINDOW)
    assert credit.shares["2"] == {key("acc-ann"): 1.0} and credit.by_dev == set()
    assert credit.shares["1"] == {key("acc-ann"): 1.0} and credit.by_pr == {"1", "3"}


def test_an_unmatched_dev_id_is_kept_like_any_unmapped_account(conn):
    seed_impact(conn)
    dev(conn, "2", "acc-nobody-knows", "acc-ann")
    credit = cr.credit_for(conn, WINDOW)
    assert credit.shares["2"] == {key("acc-nobody-knows"): 0.75, key("acc-ann"): 0.25}
    everyone = cr.scoped(conn, Scope(), credit)
    assert dict((row["key"], f) for row, f in everyone.items)["MD-2"] == pytest.approx(1.0)
    team = cr.scoped(conn, team_scope(conn, "t1"), credit)
    assert dict((row["key"], f) for row, f in team.items)["MD-2"] == pytest.approx(0.25)


def test_other_properties_with_a_similar_name_are_not_dev_fields(conn):
    seed_impact(conn)
    prop(conn, "work_item", "2", "dev1x_other", "acc-bob")
    prop(conn, "work_item", "2", "xdev1_other", "acc-bob")
    prop(conn, "work_item", "2", "developer", "acc-bob")
    assert cr.dev_shares(conn, ["2"]) == {}


def test_dev_shares_with_no_ids_is_empty(conn):
    assert cr.dev_shares(conn, []) == {}


def test_the_credit_note_mentions_dev_credited_issues(conn):
    seed_impact(conn)
    dev(conn, "2", "acc-bob")
    note = cr.credit_note(cr.credit_for(conn, WINDOW))
    assert note == (
        "1 of 5 completed issue(s) were credited to the Dev1/Dev2 fields, 2 to the authors of their linked "
        "pull requests and 2 to the assignee because no pull request is linked."
    )
    dev(conn, "1", "acc-ann")
    dev(conn, "3", "acc-ann")
    dev(conn, "2", "acc-ann")
    dev(conn, "6", "acc-ann")
    dev(conn, "7", "acc-ann")
    assert cr.credit_note(cr.credit_for(conn, WINDOW)) == (
        "5 of 5 completed issue(s) were credited to the Dev1/Dev2 fields, 0 to the authors of their linked "
        "pull requests and 0 to the assignee because no pull request is linked."
    )


def test_issues_with_dev_credit_only_are_noted_even_without_other_evidence(conn):
    seed_impact(conn)
    conn.execute("DELETE FROM link WHERE source = 'linker'")
    dev(conn, "2", "acc-bob")
    assert cr.credit_note(cr.credit_for(conn, WINDOW)).startswith("1 of 5 completed issue(s) were credited to the Dev")


def test_dev_credit_does_not_change_which_issues_are_completed(conn):
    seed_impact(conn)
    dev(conn, "8", "acc-bob")  # completed in August
    assert "8" not in cr.credit_for(conn, WINDOW).shares


def test_the_impact_fallback_uses_dev_shares_before_the_assignee(conn):
    from delivery_analysis.metrics.impact_build import rebuild_impact

    issue(conn, "U", "acc-ann", resolved="2026-09-10T12:00:00Z", points=4)
    issue(conn, "V", "acc-ann", resolved="2026-09-11T12:00:00Z", points=3)
    dev(conn, "U", "acc-bob", "acc-cy")
    rebuild_impact(conn, "2026-10-15T12:00:00Z")
    out = {(r["issue_id"], r["actor_key"]): r["delivery"] for r in conn.execute("SELECT * FROM impact_share")}
    assert out == {("U", key("acc-bob")): 3.0, ("U", key("acc-cy")): 1.0, ("V", key("acc-ann")): 3.0}


def test_a_property_that_only_starts_with_dev1_or_dev2_is_not_a_dev_field(conn):
    seed_impact(conn)
    prop(conn, "work_item", "2", "dev1_hours_customfield_10200", "acc-bob")
    prop(conn, "work_item", "2", "dev2_notes", "acc-bob")
    assert cr.dev_shares(conn, ["2"]) == {}
    dev(conn, "2", dev1="acc-ann")
    assert list(cr.dev_shares(conn, ["2"])["2"].values()) == [1.0]
