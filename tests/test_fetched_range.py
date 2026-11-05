from delivery_analysis.store import fetched_range as fr

D = "T00:00:00Z"


def test_merge_joins_overlapping_and_touching_ranges():
    ranges = [("2026-03-01" + D, "2026-04-01" + D), ("2026-01-01" + D, "2026-02-01" + D),
              ("2026-02-01" + D, "2026-02-15" + D), ("2026-04-01T12:00:00Z", "2026-05-01" + D)]
    assert fr.merge(ranges) == [("2026-01-01" + D, "2026-02-15" + D), ("2026-03-01" + D, "2026-05-01" + D)]


def test_merge_drops_backwards_and_empty_ranges():
    assert fr.merge([("2026-02-01" + D, "2026-01-01" + D), ("", "2026-01-01" + D)]) == []


def test_first_gap_none_when_covered():
    assert fr.first_gap([("2025-01-01" + D, "2026-11-05" + D)], "2025-08-12" + D, "2026-11-05" + D) is None


def test_first_gap_in_the_middle():
    ranges = [("2025-01-01" + D, "2026-01-01" + D), ("2026-03-01" + D, "2026-11-05" + D)]
    assert fr.first_gap(ranges, "2025-08-12" + D, "2026-11-05" + D) == "2026-01-01" + D


def test_first_gap_at_the_start_and_at_the_end():
    assert fr.first_gap([("2026-03-01" + D, "2026-11-05" + D)], "2025-08-12" + D, "2026-11-05" + D) == "2025-08-12" + D
    assert fr.first_gap([("2025-01-01" + D, "2026-06-01" + D)], "2025-08-12" + D, "2026-11-05" + D) == "2026-06-01" + D
    assert fr.first_gap([], "2025-08-12" + D, "2026-11-05" + D) == "2025-08-12" + D


def test_first_gap_takes_the_earliest_of_several():
    ranges = [("2025-01-01" + D, "2025-10-01" + D), ("2025-11-01" + D, "2026-01-01" + D),
              ("2026-03-01" + D, "2026-11-05" + D)]
    assert fr.first_gap(ranges, "2025-08-12" + D, "2026-11-05" + D) == "2025-10-01" + D


def test_first_gap_allows_a_day_of_slack():
    ranges = [("2025-08-12T06:00:00Z", "2026-01-01" + D), ("2026-01-01T20:00:00Z", "2026-11-04T20:00:00Z")]
    assert fr.first_gap(ranges, "2025-08-12" + D, "2026-11-05" + D) is None


def test_add_merges_in_the_store(conn):
    fr.add(conn, "jira", "ABC", "2026-01-01" + D, "2026-02-01" + D)
    fr.add(conn, "jira", "ABC", "2026-03-01" + D, "2026-04-01" + D)
    fr.add(conn, "jira", "ABC", "2026-01-15" + D, "2026-03-10" + D)
    fr.add(conn, "jira", "OTHER", "2020-01-01" + D, "2020-02-01" + D)
    assert fr.list_ranges(conn, "jira", "ABC") == [("2026-01-01" + D, "2026-04-01" + D)]
