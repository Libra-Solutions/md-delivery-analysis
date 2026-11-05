from delivery_analysis.cli.main import main


def make_env(tmp_path):
    return {"GITHUB_ANALYSIS_RESULTS": str(tmp_path)}


def run(args, tmp_path):
    return main(
        args,
        env_path=tmp_path / "missing.env",
        environ=make_env(tmp_path),
    )


def test_help_lists_commands(tmp_path, capsys):
    assert run([], tmp_path) == 0
    out = capsys.readouterr().out
    assert "cohort" in out
    assert "backfill" in out


def test_cohort_dispatch(tmp_path):
    assert main(
        ["cohort", "list"],
        env_path=tmp_path / "missing.env",
        environ=make_env(tmp_path),
    ) == 0
