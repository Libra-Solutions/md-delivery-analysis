import argparse
import dataclasses
from pathlib import Path

import pytest

from delivery_analysis.cli import backfill as backfill_cli
from delivery_analysis.settings import Settings
from delivery_analysis.sync import backfill as bf


class FakeConnector:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def calls(monkeypatch):
    seen = {}

    def fake_build(settings, environ, transport=None):
        seen["built_days"] = settings.window_days
        seen["transport"] = transport
        return [FakeConnector("bitbucket"), FakeConnector("jira"), FakeConnector("claude_code")]

    def fake_sync(conn, connectors, settings, environ, *, only=None, log=None, fetch_code=False):
        seen["sync_settings"] = settings
        seen["only"] = only
        seen["connectors"] = [c.name for c in connectors]
        if log:
            log("bitbucket/r1: ok, 3 record(s)")
        return ([], [], 0)

    monkeypatch.setattr(bf, "build_connectors", fake_build)
    monkeypatch.setattr(bf, "sync_and_reconcile", fake_sync)
    return seen


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "teams.sqlite")


def _seed_state(conn):
    for connector, scope in [("jira", "ABC"), ("jira", "DEF"), ("bitbucket", "r1"), ("claude_code", "user_cost")]:
        conn.execute(
            "INSERT INTO sync_state (connector, scope, cursor) VALUES (?, ?, '2026-10-01T00:00:00Z')",
            (connector, scope),
        )
    conn.commit()


def _scopes(conn):
    return sorted((r["connector"], r["scope"]) for r in conn.execute("SELECT connector, scope FROM sync_state"))


def test_clears_cursors(conn, settings, calls):
    _seed_state(conn)
    bf.backfill(conn, settings, {}, 450)
    assert [s for s in _scopes(conn) if s[0] != "claude_code"] == []


def test_claude_cursor_kept(conn, settings, calls):
    _seed_state(conn)
    bf.backfill(conn, settings, {}, 450)
    assert _scopes(conn) == [("claude_code", "user_cost")]


def test_connectors_built_with_days(conn, settings, calls):
    bf.backfill(conn, settings, {}, 450)
    assert calls["built_days"] == 450


def test_token_window_unchanged(conn, settings, calls):
    bf.backfill(conn, settings, {}, 450)
    assert calls["sync_settings"] is settings
    assert calls["sync_settings"].window_days == 90


def test_only_source(conn, settings, calls):
    _seed_state(conn)
    bf.backfill(conn, settings, {}, 450, only="jira")
    assert calls["only"] == "jira"
    assert _scopes(conn) == [("bitbucket", "r1"), ("claude_code", "user_cost")]


def test_days_bounds(conn, settings, calls):
    for bad in (0, 3651, -1):
        with pytest.raises(ValueError):
            bf.backfill(conn, settings, {}, bad)
    bf.backfill(conn, settings, {}, 1)
    bf.backfill(conn, settings, {}, 3650)


def test_transport_passed(conn, settings, calls):
    marker = object()
    bf.backfill(conn, settings, {}, 30, transport=marker)
    assert calls["transport"] is marker


NOW = "2026-11-05T12:00:00Z"  # 450 days back is 2025-08-12


def _bf(conn, settings, **kw):
    return bf.backfill(conn, settings, {}, 450, log=kw.pop("log", lambda _l: None), now=lambda: NOW, **kw)


def _cursor(conn, connector, scope):
    row = conn.execute("SELECT cursor FROM sync_state WHERE connector = ? AND scope = ?", (connector, scope)).fetchone()
    return row["cursor"] if row else None


def test_unconfigured_source_keeps_cursors(conn, settings, monkeypatch, calls):
    _seed_state(conn)
    monkeypatch.setattr(bf, "build_connectors", lambda s, e, t=None: [FakeConnector("jira")])
    lines = []
    _bf(conn, settings, log=lines.append)
    assert _cursor(conn, "bitbucket", "r1") == "2026-10-01T00:00:00Z"
    assert _cursor(conn, "jira", "ABC") is None
    assert any("bitbucket: not set up" in line for line in lines)


def test_marker_skips_scope(conn, settings, calls):
    from delivery_analysis.store import backfill_state

    _seed_state(conn)
    backfill_state.mark_done(conn, "jira", "ABC", "2025-08-01T00:00:00Z", NOW)
    lines = []
    _bf(conn, settings, log=lines.append)
    assert _cursor(conn, "jira", "ABC") == "2026-10-01T00:00:00Z"
    assert _cursor(conn, "jira", "DEF") is None
    assert any("jira/ABC: stored back to 2025-08-12 with no gaps" in line for line in lines)


def test_marker_too_recent_is_fetched_again(conn, settings, calls):
    from delivery_analysis.store import backfill_state

    _seed_state(conn)
    backfill_state.mark_done(conn, "jira", "ABC", "2026-01-01T00:00:00Z", NOW)
    _bf(conn, settings)
    assert _cursor(conn, "jira", "ABC") is None


def _pr(conn, repo, created):
    conn.execute(
        "INSERT INTO change_request (source, source_id, repository_id, number, state, created_at, fetched_at) "
        "VALUES ('bitbucket', ?, ?, 1, 'MERGED', ?, ?)",
        (f"{repo}#{created}", repo, created, NOW),
    )
    conn.commit()


def _weekly_prs(conn, repo, first, last, skip=None):
    """A pull request every 7 days from `first` to `last`, leaving out (start, end) when given."""
    from datetime import date, timedelta

    day = date.fromisoformat(first)
    while day <= date.fromisoformat(last):
        if not skip or not (date.fromisoformat(skip[0]) <= day <= date.fromisoformat(skip[1])):
            _pr(conn, repo, day.isoformat() + "T10:00:00Z")
        day += timedelta(days=7)


def test_stored_pull_requests_skip_repository(conn, settings, calls):
    _seed_state(conn)
    _weekly_prs(conn, "r1", "2024-03-01", "2026-09-30")
    _bf(conn, settings)
    assert _cursor(conn, "bitbucket", "r1") == "2026-10-01T00:00:00Z"


def test_one_old_pull_request_does_not_prove_the_history(conn, settings, calls):
    """The old rule (oldest record reaches back far enough) was fooled by a single old pull request."""
    _seed_state(conn)
    _pr(conn, "r1", "2024-03-01T00:00:00Z")
    _bf(conn, settings)
    assert _cursor(conn, "bitbucket", "r1") is None


def test_hole_in_pull_requests_fetches_from_the_hole(conn, settings, calls):
    _seed_state(conn)
    _weekly_prs(conn, "r1", "2024-03-01", "2026-09-30", skip=("2026-02-01", "2026-04-15"))
    lines = []
    _bf(conn, settings, log=lines.append)
    moved = _cursor(conn, "bitbucket", "r1")
    assert "2026-01-25" <= moved[:10] < "2026-02-01"  # the last pull request before the silence
    assert any("bitbucket/r1: missing data from 2026-01" in line for line in lines)


def test_short_silence_is_not_a_hole(conn, settings, calls):
    _seed_state(conn)
    _weekly_prs(conn, "r1", "2024-03-01", "2026-09-30", skip=("2026-02-01", "2026-02-10"))
    _bf(conn, settings)
    assert _cursor(conn, "bitbucket", "r1") == "2026-10-01T00:00:00Z"


def test_hole_in_recorded_ranges_fetches_from_the_hole(conn, settings, calls):
    from delivery_analysis.store import fetched_range

    _seed_state(conn)
    fetched_range.add(conn, "jira", "ABC", "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    fetched_range.add(conn, "jira", "ABC", "2026-03-01T00:00:00Z", "2026-10-01T00:00:00Z")
    _bf(conn, settings)
    assert _cursor(conn, "jira", "ABC") == "2026-01-01T00:00:00Z"


def test_recorded_ranges_that_join_up_are_skipped(conn, settings, calls):
    from delivery_analysis.store import fetched_range

    _seed_state(conn)
    fetched_range.add(conn, "jira", "ABC", "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    fetched_range.add(conn, "jira", "ABC", "2025-12-25T00:00:00Z", "2026-10-01T00:00:00Z")
    _bf(conn, settings)
    assert _cursor(conn, "jira", "ABC") == "2026-10-01T00:00:00Z"


def test_ranges_starting_after_the_window_start_fetch_everything(conn, settings, calls):
    from delivery_analysis.store import fetched_range

    _seed_state(conn)
    fetched_range.add(conn, "jira", "ABC", "2026-03-01T00:00:00Z", "2026-10-01T00:00:00Z")
    _bf(conn, settings)
    assert _cursor(conn, "jira", "ABC") is None


def test_recent_pull_requests_do_not_skip(conn, settings, calls):
    _seed_state(conn)
    _pr(conn, "r1", "2026-06-01T00:00:00Z")
    _bf(conn, settings)
    assert _cursor(conn, "bitbucket", "r1") is None


def test_force_fetches_again(conn, settings, calls):
    _seed_state(conn)
    _pr(conn, "r1", "2024-03-01T00:00:00Z")
    _bf(conn, settings, force=True)
    assert _cursor(conn, "bitbucket", "r1") is None


def _finish_sync(monkeypatch, cursors):
    def fake_sync(conn, connectors, settings, environ, *, only=None, log=None, fetch_code=False):
        for (connector, scope), cursor in cursors.items():
            conn.execute(
                "INSERT INTO sync_state (connector, scope, cursor, status) VALUES (?, ?, ?, 'ok') "
                "ON CONFLICT(connector, scope) DO UPDATE SET cursor = excluded.cursor, status = 'ok'",
                (connector, scope, cursor),
            )
        conn.commit()
        return ([], [], 0)

    monkeypatch.setattr(bf, "sync_and_reconcile", fake_sync)


def test_finished_scope_is_marked(conn, settings, monkeypatch, calls):
    from delivery_analysis.store import backfill_state

    _finish_sync(monkeypatch, {("bitbucket", "r1"): NOW, ("bitbucket", "r2"): None})
    _bf(conn, settings)
    assert backfill_state.get_since(conn, "bitbucket", "r1") == "2025-08-12T12:00:00Z"
    # Cut short by the request budget: no cursor, so not marked and fetched again next time.
    assert backfill_state.get_since(conn, "bitbucket", "r2") is None


def test_marker_keeps_earliest(conn, settings):
    from delivery_analysis.store import backfill_state

    backfill_state.mark_done(conn, "jira", "ABC", "2025-01-01T00:00:00Z", NOW)
    backfill_state.mark_done(conn, "jira", "ABC", "2025-08-01T00:00:00Z", NOW)
    assert backfill_state.get_since(conn, "jira", "ABC") == "2025-01-01T00:00:00Z"


def test_marker_does_not_span_a_hole(conn):
    from delivery_analysis.store import backfill_state

    backfill_state.mark_done(conn, "jira", "ABC", "2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z")
    backfill_state.mark_done(conn, "jira", "ABC", "2025-08-01T00:00:00Z", NOW)
    assert backfill_state.get_range(conn, "jira", "ABC") == ("2025-08-01T00:00:00Z", NOW)


def test_cut_short_hole_fill_is_not_marked(conn, settings, monkeypatch, calls):
    from delivery_analysis.store import backfill_state, fetched_range

    _seed_state(conn)
    fetched_range.add(conn, "jira", "ABC", "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    fetched_range.add(conn, "jira", "ABC", "2026-03-01T00:00:00Z", "2026-10-01T00:00:00Z")
    # The run ends "ok" but the budget ran out before a new cursor: it stays where the backfill put it.
    _finish_sync(monkeypatch, {("jira", "ABC"): "2026-01-01T00:00:00Z"})
    _bf(conn, settings)
    assert backfill_state.get_range(conn, "jira", "ABC") is None
    assert _cursor(conn, "jira", "ABC") == "2026-01-01T00:00:00Z"  # the next backfill continues from the hole


# --- end to end: the real runner, a fake source that records what it is asked for --------------------


class RecordingSource:
    """Answers every scope with one batch and a new cursor; remembers each `since` it was asked for."""

    def __init__(self, name, scopes, stop_before_cursor=()):
        self.name = name
        self._scopes = scopes
        self.asked = {}
        self._stop = set(stop_before_cursor)

    def validate(self):
        return []

    def scopes(self):
        return list(self._scopes)

    def sync(self, scope, since):
        from delivery_analysis.model.records import Batch

        self.asked[scope] = since
        if scope in self._stop:
            return  # the request budget ran out before the cursor batch
        yield Batch([], cursor=NOW)


def _real_sync(monkeypatch, source):
    from delivery_analysis.sync.runner import run_sync

    def sync(conn, connectors, settings, environ, *, only=None, log=None, fetch_code=False):
        return (run_sync(conn, [source], overlap_days=7, only=only, now=lambda: NOW), [], 0)

    monkeypatch.setattr(bf, "build_connectors", lambda s, e, t=None: [source])
    monkeypatch.setattr(bf, "sync_and_reconcile", sync)


def _state(conn, connector, scope, cursor):
    conn.execute("INSERT INTO sync_state (connector, scope, cursor) VALUES (?, ?, ?)", (connector, scope, cursor))


def test_end_to_end_only_new_data_hole_and_empty(conn, settings, monkeypatch):
    from delivery_analysis.store import fetched_range

    cursor = "2026-10-01T00:00:00Z"
    for scope in ("full", "holed", "empty"):
        _state(conn, "jira", scope, cursor)
    fetched_range.add(conn, "jira", "full", "2025-01-01T00:00:00Z", cursor)
    fetched_range.add(conn, "jira", "holed", "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    fetched_range.add(conn, "jira", "holed", "2026-03-01T00:00:00Z", cursor)
    source = RecordingSource("jira", ["full", "holed", "empty", "new"])
    _real_sync(monkeypatch, source)
    _bf(conn, settings)
    # Stored with no gaps: asked only from its cursor (less the usual 7-day overlap), never further back.
    assert source.asked["full"] == "2026-09-24T00:00:00Z"
    # A hole from 1 Jan: asked from the hole, not from the window start.
    assert source.asked["holed"] == "2025-12-25T00:00:00Z"
    # Nothing recorded, or never synced: the whole window (the connector's own start).
    assert source.asked["empty"] is None and source.asked["new"] is None


def test_end_to_end_second_backfill_fetches_nothing_old(conn, settings, monkeypatch):
    source = RecordingSource("jira", ["ABC"])
    _real_sync(monkeypatch, source)
    _bf(conn, settings)
    assert source.asked["ABC"] is None  # first backfill: whole window
    again = RecordingSource("jira", ["ABC"])
    _real_sync(monkeypatch, again)
    lines = []
    _bf(conn, settings, log=lines.append)
    assert again.asked["ABC"] == "2026-10-29T12:00:00Z"  # only from the cursor, less the overlap
    assert any("jira/ABC: stored back to 2025-08-12 with no gaps" in line for line in lines)


def test_end_to_end_cut_short_is_fetched_again(conn, settings, monkeypatch):
    source = RecordingSource("jira", ["ABC"], stop_before_cursor=["ABC"])
    _real_sync(monkeypatch, source)
    _bf(conn, settings)
    again = RecordingSource("jira", ["ABC"])
    _real_sync(monkeypatch, again)
    _bf(conn, settings)
    assert again.asked["ABC"] is None  # not finished, so the whole window again


def test_runner_records_the_range_it_fetched(conn):
    from delivery_analysis.store import fetched_range
    from delivery_analysis.sync.runner import run_sync

    _state(conn, "jira", "ABC", "2026-10-01T00:00:00Z")
    run_sync(conn, [RecordingSource("jira", ["ABC", "fresh"])], overlap_days=7, now=lambda: NOW)
    assert fetched_range.list_ranges(conn, "jira", "ABC") == [("2026-09-24T00:00:00Z", NOW)]
    assert fetched_range.list_ranges(conn, "jira", "fresh") == []  # its start is the connector's own window


def test_runner_records_nothing_when_cut_short(conn):
    from delivery_analysis.store import fetched_range
    from delivery_analysis.sync.runner import run_sync

    _state(conn, "jira", "ABC", "2026-10-01T00:00:00Z")
    run_sync(conn, [RecordingSource("jira", ["ABC"], stop_before_cursor=["ABC"])], overlap_days=7, now=lambda: NOW)
    assert fetched_range.list_ranges(conn, "jira", "ABC") == []


def test_cli_force_flag(settings, calls, monkeypatch):
    seen = {}
    monkeypatch.setattr(bf, "backfill", lambda *a, **k: seen.update(k) or ([], [], 0))
    monkeypatch.setattr(backfill_cli, "backfill", bf.backfill)
    assert _run(settings, "--force") == 0
    assert seen["force"] is True


def _run(settings, *argv):
    parser = argparse.ArgumentParser()
    backfill_cli.register(parser.add_subparsers(dest="command"))
    return backfill_cli.run(parser.parse_args(["backfill", *argv]), settings, {})


def test_cli_prints_progress(settings, calls, capsys):
    assert _run(settings, "--days", "450") == 0
    out = capsys.readouterr().out
    assert "bitbucket/r1: ok" in out
    assert calls["built_days"] == 450


def test_cli_bad_days_exits_2(settings, calls, capsys):
    assert _run(settings, "--days", "0") == 2
    assert "days" in capsys.readouterr().out.lower()


def test_cli_failed_sync_exits_1(settings, monkeypatch, calls):
    monkeypatch.setattr(bf, "sync_and_reconcile", lambda *a, **k: ([type("R", (), {"status": "failed"})()], [], 0))
    assert _run(settings, "--days", "30") == 1


def test_cli_redacts_secrets_in_errors_and_log(settings, monkeypatch, calls, capsys):
    from delivery_analysis.settings import secret_values  # noqa: F401

    def boom(*a, **k):
        k["log"]("token tok-abcdef123456 seen")
        raise RuntimeError("bad tok-abcdef123456")

    monkeypatch.setattr(bf, "sync_and_reconcile", boom)
    parser = argparse.ArgumentParser()
    backfill_cli.register(parser.add_subparsers(dest="command"))
    env = {"ATLASSIAN": "tok-abcdef123456"}
    code = backfill_cli.run(parser.parse_args(["backfill", "--days", "30"]), settings, env)
    out = capsys.readouterr().out
    assert code == 1
    assert "tok-abcdef123456" not in out
