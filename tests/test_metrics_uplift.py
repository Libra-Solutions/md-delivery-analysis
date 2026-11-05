import statistics
from datetime import date, timedelta

import pytest

from metrics_seed import REPO, TZ, person, pr, put, team
from delivery_analysis.metrics import blocks, uplift
from delivery_analysis.metrics.people import team_scope

DAY0 = date(2026, 9, 1)
TODAY = date(2026, 10, 31)  # Day 60: block 0 and 1 are complete, block 2 has one day


# Stand-ins for T9's block math, so these tests do not depend on its internals.
def fake_block_dates(day0, today, back=12):
    out = []
    for index in range(-back, 1 + max((today - day0).days // 30, 0) + 1):
        first = day0 + timedelta(days=30 * index)
        if first > today:
            break
        days = min(30, (today - first).days + 1)
        out.append({"index": index, "first": first.isoformat(), "days": days, "partial": days < 30})
    return out


def fake_summarize(values):
    if not values:
        return {"median": None, "average": None, "low": None, "high": None, "count": 0}
    return {"median": float(statistics.median(values)), "average": float(sum(values)) / len(values),
            "low": float(min(values)), "high": float(max(values)), "count": len(values)}


def fake_prorate(value, days, full=30):
    if days < 1:
        raise ValueError("days must be at least 1")
    return value * full / days


@pytest.fixture(autouse=True)
def fake_blocks(monkeypatch):
    monkeypatch.setattr(blocks, "block_dates", fake_block_dates)
    monkeypatch.setattr(blocks, "summarize", fake_summarize)
    monkeypatch.setattr(blocks, "prorate", fake_prorate)
    monkeypatch.setattr(blocks, "day_reached", lambda day0, today: (today - day0).days)


_n = [100]


def merged(conn, account, day, created_hours=24):
    _n[0] += 1
    when = f"{day}T16:00:00Z"
    start = (date.fromisoformat(day) - timedelta(days=created_hours // 24)).isoformat() + "T16:00:00Z"
    pr(conn, _n[0], account, "MERGED", start, when)


def before_day(i, offset=5):
    return (DAY0 - timedelta(days=30 * i) + timedelta(days=offset)).isoformat()


@pytest.fixture
def seeded(conn):
    person(conn, "p-ann", "Ann Example", accounts=["acc-ann"])
    person(conn, "p-bob", "Bob Builder", accounts=["acc-bob"])
    team(conn, "t1", "Core", [REPO], {"p-ann": "active", "p-bob": "active"})
    put(conn, "repository", source="bitbucket", source_id=REPO, workspace="ws", name="core", default_branch="main")
    for i in range(1, 13):  # Ann merges one PR in every before block
        merged(conn, "acc-ann", before_day(i))
    merged(conn, "acc-bob", before_day(1))  # Bob only in the nearest one
    for day in ("2026-09-05", "2026-09-10", "2026-09-15"):  # block 0
        merged(conn, "acc-ann", day)
    merged(conn, "acc-ann", "2026-10-02")  # block 1
    merged(conn, "acc-bob", "2026-09-06")
    for day in ("2026-09-07", "2026-09-08", "2026-09-09", "2026-09-11", "2026-09-12"):
        merged(conn, "acc-zed", day)  # nobody mapped this account
    return conn


def scope(conn):
    return team_scope(conn, "t1")


def test_shapes(seeded):
    out = uplift.person_blocks(seeded, "p-ann", scope(seeded), "prs_merged", DAY0, TODAY, TZ)
    assert out["metric"] == "prs_merged"
    assert set(out) >= {"metric", "blocks", "person", "everyone", "short_baseline"}
    assert set(out["person"]) == set(out["everyone"]) == {"before", "after"}
    assert set(out["person"]["after"]) == {"median", "average", "low", "high", "count"}
    block0 = next(b for b in out["blocks"] if b["index"] == 0)
    assert block0 == {"index": 0, "start": "2026-09-01", "days": 30, "partial": False,
                      "value": 3.0, "median": 2.0, "average": 2.0, "no_data": False}
    assert out["short_baseline"] is False
    assert out["person"]["before"]["median"] == 1.0
    assert out["person"]["after"]["count"] == 2  # the running block where nobody has merged yet is no data
    assert [b["index"] for b in out["blocks"] if b["no_data"]] == [2]


def test_running_block_prorated_for_sum_metric(seeded):
    merged(seeded, "acc-ann", "2026-10-31")
    out = uplift.person_blocks(seeded, "p-ann", scope(seeded), "prs_merged", DAY0, TODAY, TZ)
    running = out["blocks"][-1]
    assert running["partial"] is True and running["days"] == 1
    assert running["value"] == 30.0


def test_hours_not_prorated(seeded):
    _n[0] += 1
    pr(seeded, _n[0], "acc-ann", "MERGED", "2026-10-31T10:00:00Z", "2026-10-31T16:00:00Z")
    out = uplift.person_blocks(seeded, "p-ann", scope(seeded), "time_to_merge", DAY0, TODAY, TZ)
    running = out["blocks"][-1]
    assert running["partial"] is True
    assert running["value"] == 6.0


def test_short_baseline(seeded):
    # time_to_merge has a value only in blocks where the person merged; give Bob just one before block
    out = uplift.person_blocks(seeded, "p-bob", scope(seeded), "time_to_merge", DAY0, TODAY, TZ)
    assert out["short_baseline"] is True
    full = uplift.person_blocks(seeded, "p-ann", scope(seeded), "time_to_merge", DAY0, TODAY, TZ)
    assert full["short_baseline"] is False


def test_unmapped_excluded(seeded):
    out = uplift.person_blocks(seeded, "p-ann", scope(seeded), "prs_merged", DAY0, TODAY, TZ)
    block0 = next(b for b in out["blocks"] if b["index"] == 0)
    assert block0["median"] == 2.0 and block0["average"] == 2.0  # Ann 3, Bob 1; the 5 PRs of acc-zed are out
    assert out["everyone"]["after"]["count"] == 4  # 2 people x 2 blocks; the block nobody has PRs in is no data


def test_days_1_90_after_day_60(seeded):
    rows = uplift.windows(seeded, "p-ann", scope(seeded), "prs_merged", DAY0, TODAY, TZ)
    assert [w["label"] for w in rows] == ["Days 1-30", "Days 1-60", "Days 1-90"]
    last = rows[-1]
    assert last["days"] == 90 and last["reached"] == 60 and last["complete"] is False
    assert last["total"] == 4.0
    assert last["prorated"] == 6.0  # 4 PRs in 60 days, scaled to 90
    assert last["before_median"] == 1.0
    assert last["uplift"] == 2.0  # 6 PRs in 90 days = 2 per 30 days against a before median of 1
    assert rows[0]["complete"] is True and rows[0]["uplift"] == 3.0
    assert rows[1]["complete"] is True and rows[1]["uplift"] == 2.0


def test_zero_before_median_gives_no_uplift(seeded):
    rows = uplift.windows(seeded, "p-bob", scope(seeded), "prs_merged", DAY0, TODAY, TZ)
    assert rows[0]["before_median"] == 0.0
    assert rows[0]["uplift"] is None


def test_day0_in_future_has_no_windows(seeded):
    assert uplift.windows(seeded, "p-ann", scope(seeded), "prs_merged", date(2026, 12, 1), TODAY, TZ) == []


def test_metric_table(seeded):
    table = uplift.metric_table(seeded, "p-ann", scope(seeded), ["prs_merged", "time_to_merge"], DAY0, TODAY, TZ)
    first = table[0]
    assert first["metric"] == "prs_merged" and first["label"] == "PRs merged"
    assert first["before"] == 1.0 and first["before_median_everyone"] == 1.0  # pooled: 13 ones and 11 zeros
    assert first["windows"][0] == {"label": "Days 1-30", "value": 3.0, "median": 2.0, "uplift": 3.0}
    assert first["windows"][1]["value"] == 2.0  # 4 PRs in 60 days = 2 per 30
    assert table[1]["metric"] == "time_to_merge"


def test_unknown_metric(seeded):
    with pytest.raises(KeyError):
        uplift.windows(seeded, "p-ann", scope(seeded), "nope", DAY0, TODAY, TZ)


def test_days_1_90_hidden_before_day_60(seeded):
    rows = uplift.windows(seeded, "p-ann", scope(seeded), "prs_merged", DAY0, date(2026, 10, 15), TZ)
    assert [w["label"] for w in rows] == ["Days 1-30", "Days 1-60"]


def test_real_blocks_seam(seeded, monkeypatch):
    import importlib
    importlib.reload(blocks)  # drop the stand-ins; use T9's real block math
    monkeypatch.undo()
    out = uplift.person_blocks(seeded, "p-ann", scope(seeded), "prs_merged", DAY0, TODAY, TZ)
    block0 = next(b for b in out["blocks"] if b["index"] == 0)
    assert block0["value"] == 3.0 and block0["median"] == 2.0 and block0["partial"] is False
    assert out["person"]["before"]["median"] == 1.0
    assert out["blocks"][-1]["partial"] is True


@pytest.fixture
def three(seeded):
    person(seeded, "p-cy", "Cy Example", accounts=["acc-cy"])
    for day in ("2026-09-02", "2026-09-03", "2026-09-04", "2026-09-06", "2026-09-07", "2026-09-08"):
        merged(seeded, "acc-cy", day)  # Cy: 6 PRs in block 0
    return seeded


def _block0(out):
    return next(b for b in out["blocks"] if b["index"] == 0)


def test_group_changes_block_median_and_average(three):
    everyone = _block0(uplift.person_blocks(three, "p-ann", team_scope(three, None), "prs_merged", DAY0, TODAY, TZ))
    assert everyone["median"] == 3.0 and round(everyone["average"], 2) == 3.33  # Ann 3, Bob 1, Cy 6
    out = uplift.person_blocks(three, "p-ann", team_scope(three, None), "prs_merged", DAY0, TODAY, TZ,
                               group=["p-ann", "p-bob"])
    block0 = _block0(out)
    assert block0["value"] == 3.0  # the person's own value does not change
    assert block0["median"] == 2.0 and block0["average"] == 2.0
    assert out["everyone"]["after"]["count"] == 4  # 2 people x 2 blocks; the empty block is no data


def test_group_none_matches_default(three):
    scope_all = team_scope(three, None)
    assert (uplift.person_blocks(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ, group=None)
            == uplift.person_blocks(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ))
    assert (uplift.windows(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ, group=None)
            == uplift.windows(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ))


def test_group_outside_the_person_leaves_them_out_of_the_pool(three):
    out = uplift.person_blocks(three, "p-ann", team_scope(three, None), "prs_merged", DAY0, TODAY, TZ,
                               group=["p-bob", "p-cy"])
    block0 = _block0(out)
    assert block0["value"] == 3.0 and block0["median"] == 3.5 and block0["average"] == 3.5  # Bob 1 and Cy 6


def test_group_applies_to_windows_and_table(three):
    scope_all = team_scope(three, None)
    everyone = uplift.windows(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ)[0]
    grouped = uplift.windows(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ, group=["p-ann", "p-bob"])[0]
    assert everyone["median"] == 3.0 and grouped["median"] == 2.0
    assert grouped["total"] == everyone["total"] == 3.0
    table = uplift.metric_table(three, "p-ann", scope_all, ["prs_merged"], DAY0, TODAY, TZ)[0]
    chosen = uplift.metric_table(three, "p-ann", scope_all, ["prs_merged"], DAY0, TODAY, TZ,
                                 group=["p-ann", "p-bob"])[0]
    assert table["before_median_everyone"] == 0.0 and chosen["before_median_everyone"] == 1.0
    assert table["before"] == chosen["before"]
    assert chosen["windows"][0]["median"] == 2.0 and table["windows"][0]["median"] == 3.0


def test_group_with_nobody_in_scope_falls_back_to_everyone(three):
    scope_all = team_scope(three, None)
    plain = uplift.person_blocks(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ)
    assert uplift.person_blocks(three, "p-ann", scope_all, "prs_merged", DAY0, TODAY, TZ, group=["p-nobody"]) == plain
