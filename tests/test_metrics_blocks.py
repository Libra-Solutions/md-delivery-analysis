from datetime import date

import pytest

from delivery_analysis.metrics import blocks


def test_example_blocks():
    assert blocks.block_dates(date(2026, 9, 19), date(2026, 11, 4), back=1) == [
        {"index": -1, "first": "2026-08-20", "days": 30, "partial": False},
        {"index": 0, "first": "2026-09-19", "days": 30, "partial": False},
        {"index": 1, "first": "2026-10-19", "days": 17, "partial": True}]


def test_today_on_block_start():
    out = blocks.block_dates(date(2026, 9, 19), date(2026, 10, 19), back=0)
    assert out[-1] == {"index": 1, "first": "2026-10-19", "days": 1, "partial": True}


def test_day0_in_future():
    out = blocks.block_dates(date(2026, 12, 1), date(2026, 11, 4), back=2)
    assert [b["index"] for b in out] == [-2, -1]
    assert all(not b["partial"] for b in out)


def test_summarize():
    assert blocks.summarize([10, 20, 60]) == {"median": 20.0, "average": 30.0, "low": 10.0,
                                              "high": 60.0, "count": 3}


def test_summarize_empty():
    assert blocks.summarize([]) == {"median": None, "average": None, "low": None, "high": None, "count": 0}


def test_prorate():
    assert blocks.prorate(22, 16) == 41.25


def test_prorate_zero_days():
    with pytest.raises(ValueError):
        blocks.prorate(5, 0)


def test_day_reached():
    assert blocks.day_reached(date(2026, 9, 19), date(2026, 11, 4)) == 46
