import pytest

from metrics_seed import REPO, SEPT, TODAY, TZ, commit, seed
from delivery_analysis.metrics import quality
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
ANN = "bitbucket:acc-ann"


def files(conn, sha, pr_n, *paths, merge=False):
    commit(conn, sha, "acc-ann", "ann@corp.example", "2026-09-02T12:00:00Z", merge=merge)
    conn.execute("UPDATE vcs_commit SET change_request_id = ? WHERE sha = ?", (f"{REPO}#{pr_n}", sha))
    for path in paths:
        conn.execute(
            "INSERT INTO commit_file (repository_id, sha, path, fetched_at) VALUES (?, ?, ?, 'x')", (REPO, sha, path)
        )


@pytest.fixture
def seeded(conn):
    seed(conn)
    return conn


def pairs(obs):
    return sorted(obs.pairs.get(ANN, []))


def test_layers_of():
    assert quality.layers_of("movedocs-spa/app/x.ts") == "front"
    assert quality.layers_of("src/Api/Foo.cs") == "back"
    assert quality.layers_of("Database/x.txt") == "db"
    assert quality.layers_of("migrations/0001.sql") == "db"
    assert quality.layers_of("README.md") == ""


def test_tests_share(seeded):
    files(seeded, "f1", 1, "src/Foo.cs", "tests/FooTests.cs")
    files(seeded, "f2", 2, "src/Bar.cs")
    assert pairs(quality.prs_with_tests(seeded, Scope(), WINDOW)) == [(0.0, 1.0, 1), (1.0, 1.0, 1)]


def test_multi_layer(seeded):
    files(seeded, "f1", 1, "src/Foo.cs", "movedocs-spa/a.ts")
    files(seeded, "f2", 2, "src/Bar.cs")
    assert pairs(quality.prs_multi_layer(seeded, Scope(), WINDOW)) == [(0.0, 1.0, 1), (1.0, 1.0, 1)]


def test_layer_shares(seeded):
    files(seeded, "f1", 1, "src/Foo.cs", "movedocs-spa/a.ts", "db/x.sql")
    files(seeded, "f2", 2, "src/Bar.cs")
    assert pairs(quality.prs_front_end(seeded, Scope(), WINDOW)) == [(0.0, 1.0, 1), (1.0, 1.0, 1)]
    assert pairs(quality.prs_back_end(seeded, Scope(), WINDOW)) == [(1.0, 1.0, 1), (1.0, 1.0, 1)]
    assert pairs(quality.prs_database(seeded, Scope(), WINDOW)) == [(0.0, 1.0, 1), (1.0, 1.0, 1)]


def test_pr_without_files_excluded(seeded):
    files(seeded, "f1", 1, "src/Foo.cs")
    obs = quality.prs_with_tests(seeded, Scope(), WINDOW)
    assert len(pairs(obs)) == 1
    assert any("no file data" in note for note in obs.notes)


def test_merge_commits_ignored(seeded):
    files(seeded, "f1", 1, "src/Foo.cs")
    files(seeded, "f2", 1, "tests/FooTests.cs", merge=True)
    assert pairs(quality.prs_with_tests(seeded, Scope(), WINDOW)) == [(0.0, 1.0, 1)]


def test_window_by_merged_at(seeded):
    # PR 5 (Bob) merged in August: outside September even though it has files
    files(seeded, "f1", 5, "src/Foo.cs")
    assert quality.prs_back_end(seeded, Scope(), WINDOW).pairs == {}


def test_empty_window_has_no_pairs(conn):
    assert quality.prs_with_tests(conn, Scope(), WINDOW).pairs == {}
