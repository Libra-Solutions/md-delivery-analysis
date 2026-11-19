from datetime import date

from impact_seed import issue, seed_impact
from metrics_seed import TZ, prop
from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.weekly_points import weekly_points

END = date(2026, 9, 23)  # a Wednesday; its week starts Sep 21


def pid(conn, account):
    return People(conn).resolve(f"jira:{account}|bitbucket:{account}")


def test_points_land_in_the_week_they_were_delivered_with_no_weighting(conn):
    seed_impact(conn)
    ann = pid(conn, "acc-ann")
    d = weekly_points(conn, ann, Scope(), end=END, weeks=3, tz=TZ)
    assert d["weeks"] == ["2026-09-07", "2026-09-14", "2026-09-21"]
    assert d["running"] == "2026-09-21"
    assert d["points"][0] == 5.0  # issue 1, 5 points, Sep 10


def test_dev_fields_split_points_and_median_and_average_count_zeros(conn):
    seed_impact(conn)
    issue(conn, "20", "acc-ann", resolved="2026-09-22T14:00:00Z", points=4)
    prop(conn, "work_item", "20", "dev1_10100", "acc-ann")
    prop(conn, "work_item", "20", "dev2_10101", "acc-bob")
    ann, bob = pid(conn, "acc-ann"), pid(conn, "acc-bob")
    d = weekly_points(conn, ann, Scope(), end=END, weeks=1, tz=TZ, group=[ann, bob])
    assert d["points"] == [2.0]
    assert d["median"] == [2.0] and d["average"] == [2.0]
    assert d["comparison"] == {"custom": True, "size": 2}
    solo = weekly_points(conn, ann, Scope(), end=END, weeks=1, tz=TZ, group=[ann])
    assert solo["average"] == [2.0]
