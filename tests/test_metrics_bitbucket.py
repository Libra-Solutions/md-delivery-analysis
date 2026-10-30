import pytest

from metrics_seed import SEPT, TODAY, TZ, seed
from delivery_analysis.metrics.catalog import BY_NAME, METRICS
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.registry import PER_PERSON, run_metric
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)


@pytest.fixture
def seeded(conn):
    seed(conn)
    return conn


def run(conn, name, include_inactive=False):
    return run_metric(conn, BY_NAME[name], team_scope(conn, "t1", include_inactive), WINDOW)


def table(result):
    return [(row["name"], row["value"], row["sample"], row["rank"]) for row in result["rows"]]


def test_prs_merged_counts_team_repos_in_the_local_window(seeded):
    result = run(seeded, "prs_merged")
    assert table(result) == [("Ann Example", 3.0, 3, 1), ("Bob Builder", 0.0, 0, None)]
    bob = result["rows"][1]
    assert (bob["previous"], bob["trend"]) == (1.0, -1.0)


def test_inactive_members_appear_only_when_asked(seeded):
    names = [row["name"] for row in run(seeded, "prs_merged", include_inactive=True)["rows"]]
    assert "Cy Inactive" in names
    assert "Cy Inactive" not in [row["name"] for row in run(seeded, "prs_merged")["rows"]]


def test_time_to_merge_is_a_median_with_p85_and_an_approximation_note(seeded):
    result = run(seeded, "time_to_merge")
    assert table(result)[0] == ("Ann Example", 24.0, 3, 1)
    assert result["team"] == {"value": 24.0, "sample": 3, "p85": 40.8, "previous": 24.0, "trend": 0.0}
    assert any("1 merge times are approximate" in note for note in result["notes"])


def test_reviews_given_excludes_own_comments_and_keeps_unmapped_reviewers(seeded):
    result = run(seeded, "reviews_given")
    assert table(result) == [
        ("Ann Example", 0.0, 0, None), ("Bob Builder", 1.0, 1, None), ("Unmapped (1 account)", 1.0, 1, None)
    ]
    assert any("covers 4 of 5" in note for note in result["notes"])


def test_reviews_assigned_and_response_rate(seeded):
    assigned = run(seeded, "reviews_assigned")
    assert table(assigned) == [
        ("Ann Example", 1.0, 1, None), ("Bob Builder", 2.0, 2, None), ("Unmapped (1 account)", 1.0, 1, None)
    ]
    rate = run(seeded, "review_response_rate")
    assert [(row["name"], row["value"], row["sample"]) for row in rate["rows"]] == [
        ("Ann Example", 0.0, 1), ("Bob Builder", 0.5, 2), ("Unmapped (1 account)", 0.0, 1)
    ]


def test_review_load_counts_pending_reviews_on_open_pull_requests_now(seeded):
    result = run(seeded, "review_load")
    assert table(result) == [("Ann Example", 1.0, 1, 1), ("Bob Builder", 0.0, 0, 2)]
    assert result["rows"][0]["previous"] is None


def test_commits_skip_merges_bots_and_non_members_and_match_by_email(seeded):
    assert table(run(seeded, "commits")) == [("Ann Example", 2.0, 2, None), ("Bob Builder", 0.0, 0, None)]


def test_work_in_progress_counts_open_pull_requests(seeded):
    assert table(run(seeded, "work_in_progress")) == [("Bob Builder", 1.0, 1, 1), ("Ann Example", 0.0, 0, 2)]


def test_prs_merged_weekly_buckets_by_local_week(seeded):
    result = run(seeded, "prs_merged_weekly")
    assert [(row["week"], row["value"]) for row in result["rows"]] == [
        ("2026-08-31", 1), ("2026-09-07", 1), ("2026-09-14", 1), ("2026-09-21", 0), ("2026-09-28", 0)
    ]


def test_lead_time_breakdown_uses_only_detailed_pull_requests_with_an_approval(seeded):
    result = run(seeded, "lead_time_breakdown")
    assert result["rows"] == [
        {"part": "Waiting for first review", "median_hours": 2.0, "count": 1},
        {"part": "First review to approval", "median_hours": 4.0, "count": 1},
        {"part": "Approval to merge", "median_hours": 18.0, "count": 1},
    ]
    assert result["notes"] == ["Based on 1 of 3 merged pull requests that have an approval and review detail."]


def test_without_a_team_other_repositories_count_too(seeded):
    result = run_metric(seeded, BY_NAME["prs_merged"], Scope(), WINDOW)
    assert table(result)[0] == ("Ann Example", 4.0, 4, 1)


def test_the_catalog_has_every_planned_metric_and_waiting_ones_are_waiting(seeded):
    names = {metric.name for metric in METRICS}
    assert {"prs_merged", "time_to_merge", "reviews_given", "reviews_assigned", "review_response_rate",
            "review_load", "commits", "work_in_progress", "prs_merged_weekly", "lead_time_breakdown",
            "issues_done", "issues_done_weekly", "cycle_time", "story_points_done", "qa_points_done", "cost_spent",
            "story_points_per_dollar", "unattributed_cost_share", "ask_generate_ratio",
            "impact_points", "impact_per_dollar", "delivery_points", "delivery_speed", "durability", "participation_points", "prs_reviewed", "review_value", "review_responsiveness", "review_follow_through", "prs_with_issue_link", "documentation_activity", "story_points_weekly", "points_by_type", "cycle_time_weekly", "cycle_time_summary", "prs_linked_weekly",
            "story_points_per_dollar_all_in", "story_points_per_dollar_weekly", "cost_by_purpose_weekly"} == names
    waiting = run(seeded, "story_points_per_dollar")
    assert waiting["status"] == "waiting" and waiting["missing"] == ["jira", "claude_usage"]
    assert all(metric.kind in (PER_PERSON, "team_series", "team_breakdown") for metric in METRICS)
