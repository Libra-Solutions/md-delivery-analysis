from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from delivery_analysis.code.clone import CodeError, ensure_clone, git_env, repo_dir
from delivery_analysis.settings import redact
from tests.git_fakes import git, make_repo, shas

TOKEN = "tok-secret-123"
HEADER = base64.b64encode(("x-bitbucket-api-token-auth:" + TOKEN).encode()).decode()


def _url(path: Path) -> str:
    return path.resolve().as_posix()


def test_repo_dir_strips_braces(tmp_path):
    got = repo_dir(tmp_path, "{1234-abcd}")
    assert got == tmp_path / "code" / "1234-abcd"
    assert repo_dir(tmp_path, "1234-abcd") == got


def test_git_env_bare_token_uses_default_user():
    env = git_env(TOKEN)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_1"] == "core.longpaths"
    assert env["GIT_CONFIG_VALUE_1"] == "true"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Basic " + HEADER


def test_git_env_access_token_uses_x_token_auth():
    access = "ATCTT-made-up-access-token"
    env = git_env(access)
    expected = base64.b64encode(("x-token-auth:" + access).encode()).decode()
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Basic " + expected


def test_git_env_email_token_sent_as_is():
    env = git_env("ada@dev.example:" + TOKEN)
    expected = base64.b64encode(("ada@dev.example:" + TOKEN).encode()).decode()
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Basic " + expected


def test_clone_then_fetch(tmp_path):
    origin = make_repo(tmp_path, [{"files": {"a.py": "x = 1\n"}}])
    dest = tmp_path / "work" / "clone"
    first = ensure_clone(_url(origin), dest, TOKEN)
    assert first.fetched is False
    assert first.path == dest
    assert first.head_sha == shas(origin)[-1]
    assert (dest / "a.py").exists()

    git(origin, "checkout", "-q", "-b", "feature")
    (origin / "b.py").write_text("y = 2\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "more")
    second = ensure_clone(_url(origin), dest, TOKEN)
    assert second.fetched is True
    git(dest, "cat-file", "-e", shas(origin)[-1] + "^{commit}")


def test_clone_config_has_no_credentials(tmp_path):
    origin = make_repo(tmp_path, [{"files": {"a.py": "x = 1\n"}}])
    dest = tmp_path / "clone"
    ensure_clone(_url(origin), dest, TOKEN)
    ensure_clone(_url(origin), dest, TOKEN)
    config = (dest / ".git" / "config").read_text(encoding="utf-8")
    assert TOKEN not in config
    assert HEADER not in config
    assert "extraHeader" not in config


def test_credentials_only_in_env_not_argv(tmp_path):
    origin = make_repo(tmp_path, [{"files": {"a.py": "x = 1\n"}}])
    calls = []

    def spy(argv, **kwargs):
        calls.append((list(argv), kwargs.get("env")))
        return subprocess.run(argv, **kwargs)

    dest = tmp_path / "c"
    ensure_clone(_url(origin), dest, TOKEN, run=spy)
    ensure_clone(_url(origin), dest, TOKEN, run=spy)
    assert len(calls) >= 2
    for argv, env in calls:
        assert all(TOKEN not in part and HEADER not in part for part in argv)
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert HEADER in env["GIT_CONFIG_VALUE_0"]


def test_failure_message_is_redacted(tmp_path):
    def failing(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            128,
            stdout="",
            stderr="fatal: unable to access 'https://u:%s@bitbucket.org/w/r.git/': "
            "Authorization: Basic %s denied" % (TOKEN, HEADER),
        )

    with pytest.raises(CodeError) as err:
        ensure_clone("https://bitbucket.org/w/r.git", tmp_path / "c", TOKEN, run=failing)
    text = str(err.value)
    assert TOKEN not in text
    assert HEADER not in text
    assert "***" in text


def test_missing_git_is_plain_error(tmp_path):
    def nogit(argv, **kwargs):
        raise FileNotFoundError("git")

    with pytest.raises(CodeError) as err:
        ensure_clone("x", tmp_path / "c", TOKEN, run=nogit)
    assert "git" in str(err.value).lower()
    assert redact(str(err.value), [TOKEN]) == str(err.value)


def test_failed_clone_does_not_block_retry(tmp_path):
    dest = tmp_path / "c"
    with pytest.raises(CodeError):
        ensure_clone(_url(tmp_path / "does-not-exist"), dest, TOKEN)
    origin = make_repo(tmp_path, [{"files": {"a.py": "x\n"}}])
    assert ensure_clone(_url(origin), dest, TOKEN).fetched is False


def test_second_ensure_clone_moves_checkout_to_remote_default_branch(tmp_path):
    from delivery_analysis.code import graph

    origin = make_repo(tmp_path, [{"files": {"a.py": "x = 1\n"}}])
    dest = tmp_path / "work" / "clone"
    ensure_clone(_url(origin), dest, TOKEN)
    (origin / "new.py").write_text("y = 2\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "more")
    second = ensure_clone(_url(origin), dest, TOKEN)
    assert second.fetched is True
    assert second.head_sha == shas(origin)[-1]
    assert git(dest, "rev-parse", "HEAD") == shas(origin)[-1]
    assert (dest / "new.py").exists()
    tracked = git(dest, "ls-files").splitlines()
    assert "new.py" in tracked
