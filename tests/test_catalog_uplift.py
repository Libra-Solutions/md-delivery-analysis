from delivery_analysis.metrics import catalog
from delivery_analysis.metrics.registry import PER_PERSON

NEW_NAMES = [
    "prs_with_tests", "prs_multi_layer", "prs_front_end", "prs_back_end", "prs_database",
    "comments_received_per_pr", "inline_comments_given", "teammates_reviewed",
    "big_tickets", "points_by_merge_date",
]
RATIO_NAMES = ["prs_with_tests", "prs_multi_layer", "prs_front_end", "prs_back_end", "prs_database",
               "comments_received_per_pr"]


def test_new_metrics_listed():
    for name in NEW_NAMES:
        metric = catalog.BY_NAME[name]
        assert metric.kind == PER_PERSON
        assert metric.group == "uplift"
        assert metric.compute is not None
    assert catalog.BY_NAME["comments_received_per_pr"].better == "lower"
    assert catalog.BY_NAME["big_tickets"].needs == ("jira",)
    assert catalog.BY_NAME["points_by_merge_date"].needs == ("jira", "bitbucket")


def test_ratio_aggregates():
    for name in RATIO_NAMES:
        metric = catalog.BY_NAME[name]
        assert metric.aggregate == "ratio"
        assert metric.unit == "ratio"
