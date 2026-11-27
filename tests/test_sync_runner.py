import sqlite3

import pytest

from delivery_analysis.connectors.fake import FakeConnector
from delivery_analysis.model.records import Batch, Record
from delivery_analysis.store import db
from delivery_analysis.store import sync_state as ss
from delivery_analysis.store import upsert as up
from delivery_analysis.sync import runner

CLOCK = lambda: "2026-05-20T00:00:00Z"  # noqa: E731


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "d.sqlite")
    db.migrate(connection)
    yield connection
    connection.close()


def rec(n, source="fake", **extra):
    values = {"source": source, "source_id": str(n), "key": f"MD-{n}"}
    values.update(extra)
    return Record("work_item", values)


def rows(conn):
    return [r["source_id"] for r in conn.execute("SELECT source_id FROM work_item ORDER BY source_id")]


def test_shift_cursor_subtracts_days_and_tolerates_junk():
    assert runner.shift_cursor("2026-05-10T00:00:00Z", 7) == "2026-05-03T00:00:00Z"
    assert runner.shift_cursor(None, 7) is None
    assert runner.shift_cursor("", 7) is None
    assert runner.shift_cursor("garbage", 7) is None


def test_successful_run_stores_rows_cursor_and_health(conn):
    fake = FakeConnector(batches={"main": [Batch([rec(1), rec(2)], cursor="2026-05-10T00:00:00Z")]})
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert [(r.status, r.records, r.error) for r in results] == [("ok", 2, None)]
    assert rows(conn) == ["1", "2"]
    assert ss.get_cursor(conn, "fake", "main") == "2026-05-10T00:00:00Z"
    state = ss.list_sync_states(conn)[0]
    assert (state["status"], state["stale"], state["records"]) == ("ok", False, 2)


def test_second_run_is_idempotent_and_applies_the_overlap_window(conn):
    fake = FakeConnector(batches={"main": [Batch([rec(1)], cursor="2026-05-10T00:00:00Z")]})
    runner.run_sync(conn, [fake], overlap_hours=168, now=CLOCK)
    runner.run_sync(conn, [fake], overlap_hours=168, now=CLOCK)
    assert rows(conn) == ["1"]
    assert fake.calls == [("main", None), ("main", "2026-05-03T00:00:00Z")]


def test_default_resync_starts_two_hours_before_the_cursor_not_days(conn):
    fake = FakeConnector(batches={"main": [Batch([rec(1)], cursor="2026-05-10T00:00:00Z")]})
    runner.run_sync(conn, [fake], now=CLOCK)
    runner.run_sync(conn, [fake], now=CLOCK)
    assert fake.calls[1] == ("main", "2026-05-09T22:00:00Z")


def test_failure_after_a_good_batch_keeps_that_batch_and_marks_stale(conn):
    fake = FakeConnector(
        batches={"main": [Batch([rec(1)], cursor="c1"), Batch([rec(2)], cursor="c2")]},
        fail_on_batch=1,
        fail_message="source down",
    )
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert (results[0].status, results[0].error) == ("failed", "source down")
    assert rows(conn) == ["1"]
    assert ss.get_cursor(conn, "fake", "main") == "c1"
    assert ss.list_sync_states(conn)[0]["stale"] is True


def test_a_batch_that_fails_while_writing_leaves_no_partial_rows_or_cursor(conn):
    bad = Record("work_item", {"source": "fake", "source_id": "9", "no_such_column": 1})
    fake = FakeConnector(
        batches={"main": [Batch([rec(1)], cursor="c1"), Batch([rec(2), bad], cursor="c2")]}
    )
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert results[0].status == "failed"
    assert "no_such_column" in results[0].error
    assert rows(conn) == ["1"]
    assert ss.get_cursor(conn, "fake", "main") == "c1"
    assert not conn.in_transaction


def test_one_failing_source_does_not_block_another(conn):
    broken = FakeConnector(name="broken", batches={"main": [Batch([rec(1, "broken")])]}, fail_on_batch=0)
    healthy = FakeConnector(name="healthy", batches={"main": [Batch([rec(5, "healthy")], cursor="h1")]})
    results = {r.connector: r.status for r in runner.run_sync(conn, [broken, healthy], now=CLOCK)}
    assert results == {"broken": "failed", "healthy": "ok"}
    assert rows(conn) == ["5"]


def test_missing_or_unparseable_cursor_means_a_full_sync(conn):
    ss.set_cursor(conn, "fake", "main", "garbage")
    fake = FakeConnector(batches={"main": [Batch([rec(1)])]})
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert results[0].status == "ok"
    assert fake.calls == [("main", None)]


def test_a_token_in_an_error_message_is_redacted_everywhere(conn):
    fake = FakeConnector(
        batches={"main": [Batch([rec(1)])]},
        fail_on_batch=0,
        fail_message="401 for token sk-live-123",
    )
    messages = []
    results = runner.run_sync(conn, [fake], redact_values=["sk-live-123"], now=CLOCK, log=messages.append)
    assert "sk-live-123" not in results[0].error
    assert "***" in results[0].error
    assert "sk-live-123" not in ss.list_sync_states(conn)[0]["error"]
    assert all("sk-live-123" not in message for message in messages)


def test_only_runs_the_named_connector(conn):
    first = FakeConnector(name="first", batches={"main": [Batch([rec(1, "first")])]})
    second = FakeConnector(name="second", batches={"main": [Batch([rec(2, "second")])]})
    results = runner.run_sync(conn, [first, second], only="second", now=CLOCK)
    assert [r.connector for r in results] == ["second"]
    assert first.calls == []


def test_unmapped_identities_show_up_after_a_sync(conn):
    fake = FakeConnector(batches={"main": [Batch([rec(1, assignee_account="acc-9")])]})
    runner.run_sync(conn, [fake], now=CLOCK)
    assert up.unmapped_identities(conn) == [("fake", "acc-9")]


def test_two_sources_writing_many_batches_at_once_lose_nothing(conn):
    def many(name):
        batches = [Batch([rec(f"{name}-{i}", name)], cursor=f"c{i}") for i in range(25)]
        return FakeConnector(name=name, batches={"main": batches})

    results = runner.run_sync(conn, [many("a"), many("b")], now=CLOCK)
    assert all(r.status == "ok" for r in results)
    assert len(rows(conn)) == 50


class BrokenDiscovery:
    name = "broken"

    def validate(self):
        return []

    def scopes(self):
        raise RuntimeError("scope discovery down tok-9")

    def sync(self, scope, since):
        return iter(())


def test_a_connector_failing_scope_discovery_does_not_block_others(conn):
    healthy = FakeConnector(name="healthy", batches={"main": [Batch([rec(5, "healthy")], cursor="h1")]})
    results = runner.run_sync(conn, [BrokenDiscovery(), healthy], redact_values=["tok-9"], now=CLOCK)
    by_connector = {r.connector: r for r in results}
    assert by_connector["healthy"].status == "ok"
    assert rows(conn) == ["5"]
    broken = by_connector["broken"]
    assert (broken.scope, broken.status, broken.records) == ("*", "failed", 0)
    assert "***" in broken.error and "tok-9" not in broken.error
    state = [s for s in ss.list_sync_states(conn) if s["connector"] == "broken"][0]
    assert (state["scope"], state["stale"]) == ("*", True)
    assert "tok-9" not in state["error"]


def test_failing_to_record_a_failure_does_not_discard_other_results(conn, monkeypatch):
    real_save_state = runner.sync_state.save_state

    def flaky_save_state(*args, **kwargs):
        if kwargs.get("status") == "failed":
            raise sqlite3.OperationalError("database is locked")
        return real_save_state(*args, **kwargs)

    monkeypatch.setattr("delivery_analysis.sync.runner.sync_state.save_state", flaky_save_state)
    failing = FakeConnector(
        name="failing",
        batches={"main": [Batch([rec(1, "failing")])]},
        fail_on_batch=0,
        fail_message="source down",
    )
    healthy = FakeConnector(name="healthy", batches={"main": [Batch([rec(5, "healthy")], cursor="h1")]})
    results = {r.connector: r for r in runner.run_sync(conn, [failing, healthy], now=CLOCK)}
    assert (results["failing"].status, results["failing"].error) == ("failed", "source down")
    assert results["healthy"].status == "ok"
    assert rows(conn) == ["5"]


# ---- final fix wave ----


def test_validation_problems_fail_that_connector_only(conn):
    broken = FakeConnector(name="broken", problems=["token missing"])
    healthy = FakeConnector(name="healthy", batches={"main": [Batch([rec(5, "healthy")], cursor="h1")]})
    results = runner.run_sync(conn, [broken, healthy], now=CLOCK)
    assert [(r.connector, r.scope, r.status, r.records, r.error) for r in results] == [
        ("broken", "*", "failed", 0, "token missing"),
        ("healthy", "main", "ok", 1, None),
    ]
    assert broken.calls == []
    state = [s for s in ss.list_sync_states(conn) if s["connector"] == "broken"][0]
    assert (state["scope"], state["stale"]) == ("*", True)


def test_validate_that_raises_fails_that_connector_only(conn):
    class Raising(FakeConnector):
        def validate(self):
            raise RuntimeError("cannot check")

        def scopes(self):
            raise AssertionError("scopes must not be called")

    healthy = FakeConnector(name="healthy", batches={"main": [Batch([rec(5, "healthy")])]})
    results = runner.run_sync(conn, [Raising(name="raising"), healthy], now=CLOCK)
    assert [(r.connector, r.scope, r.status, r.error) for r in results] == [
        ("raising", "*", "failed", "cannot check"),
        ("healthy", "main", "ok", None),
    ]


def test_validation_problem_text_is_redacted(conn):
    broken = FakeConnector(name="broken", problems=["bad tok-SECRET-1", "other"])
    results = runner.run_sync(conn, [broken], redact_values=["tok-SECRET-1"], now=CLOCK)
    assert results[0].error == "bad ***; other"
    state = ss.list_sync_states(conn)[0]
    assert "tok-SECRET-1" not in state["error"]


def test_validation_respects_only(conn):
    class Boom(FakeConnector):
        def validate(self):
            raise AssertionError("must not be validated")

    other = Boom(name="other")
    wanted = FakeConnector(name="wanted", batches={"main": [Batch([rec(1, "wanted")])]})
    results = runner.run_sync(conn, [other, wanted], only="wanted", now=CLOCK)
    assert [(r.connector, r.status) for r in results] == [("wanted", "ok")]


def test_successful_discovery_clears_a_stale_star_row(conn):
    class Switchable(FakeConnector):
        fail = True

        def scopes(self):
            if self.fail:
                raise RuntimeError("discovery down")
            return super().scopes()

    src = Switchable(name="src", batches={"ok": [Batch([rec(1, "src")])]})
    first = runner.run_sync(conn, [src], now=CLOCK)
    assert [(r.scope, r.status) for r in first] == [("*", "failed")]
    src.fail = False
    second = runner.run_sync(conn, [src], now=CLOCK)
    assert [(r.scope, r.status) for r in second] == [("ok", "ok")]
    states = ss.list_sync_states(conn)
    assert [(s["scope"], s["status"]) for s in states] == [("ok", "ok")]


def test_clear_state_deletes_one_row(conn):
    ss.save_state(conn, "c", "*", status="failed", error="x", records=0, now=CLOCK())
    ss.save_state(conn, "c", "s", status="ok", error=None, records=1, now=CLOCK())
    ss.clear_state(conn, "c", "*")
    assert [s["scope"] for s in ss.list_sync_states(conn)] == ["s"]


def test_one_thread_per_connector_runs_its_scopes_in_order(conn):
    import threading

    class Recording(FakeConnector):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.threads = []

        def sync(self, scope, since):
            self.threads.append((scope, threading.get_ident()))
            return super().sync(scope, since)

    batches = {s: [Batch([rec(i, "multi")])] for i, s in enumerate(["a", "b", "c"], start=1)}
    multi = Recording(name="multi", batches=batches)
    results = runner.run_sync(conn, [multi], now=CLOCK)
    assert [(r.scope, r.status) for r in results] == [("a", "ok"), ("b", "ok"), ("c", "ok")]
    assert [scope for scope, _ in multi.threads] == ["a", "b", "c"]
    assert len({ident for _, ident in multi.threads}) == 1


def test_results_are_failures_first_then_connector_then_scope_order(conn):
    first = FakeConnector(name="first", batches={"a": [], "b": []})
    broken = FakeConnector(name="broken", problems=["nope"])
    second = FakeConnector(name="second", batches={"x": []})
    results = runner.run_sync(conn, [first, broken, second], now=CLOCK)
    assert [(r.connector, r.scope) for r in results] == [
        ("broken", "*"),
        ("first", "a"),
        ("first", "b"),
        ("second", "x"),
    ]


def test_a_failing_log_callback_never_breaks_the_run(conn):
    def bad_log(message):
        raise RuntimeError("log sink down")

    fake = FakeConnector(batches={"main": [Batch([rec(1)], cursor="c1")]})
    broken = FakeConnector(name="broken", problems=["nope"])
    results = runner.run_sync(conn, [broken, fake], now=CLOCK, log=bad_log)
    assert [(r.connector, r.status) for r in results] == [("broken", "failed"), ("fake", "ok")]
    assert rows(conn) == ["1"]
