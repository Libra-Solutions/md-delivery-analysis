"""The served app runs each refresh in its own process, so a long sync cannot starve API requests."""

from delivery_analysis.app import refresh
from delivery_analysis.app.server import create_app
from delivery_analysis.settings import Settings


def test_isolated_runner_returns_the_child_summary(tmp_path):
    db = tmp_path / "d.sqlite"
    run = refresh.isolated_sync_runner(db, Settings(db_path=db), {})
    assert run(None, False) == "No connectors are configured."


def test_isolated_runner_runs_in_another_process(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(refresh, "ProcessPoolExecutor", _Recorder(seen))
    db = tmp_path / "d.sqlite"
    refresh.isolated_sync_runner(db, Settings(db_path=db), {"A": "1"})(None, True)
    assert seen and seen[0][0] is refresh._run_in_child
    assert seen[0][1] == (db, Settings(db_path=db), {"A": "1"}, None, True)


def test_serve_style_app_uses_the_isolated_runner(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("delivery_analysis.app.server.isolated_sync_runner",
                        lambda *a: calls.append(a) or (lambda s, f: "ok"))
    create_app(tmp_path / "d.sqlite", isolate_sync=True)
    assert len(calls) == 1
    calls.clear()
    create_app(tmp_path / "e.sqlite")
    assert calls == []


class _Recorder:
    def __init__(self, seen):
        self.seen = seen

    def __call__(self, **kwargs):
        seen = self.seen

        class Pool:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def submit(self, fn, *args):
                seen.append((fn, args))

                class Done:
                    def result(self):
                        return "ok"
                return Done()
        return Pool()
