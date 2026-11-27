from pathlib import Path

from delivery_analysis import settings as s


def test_parse_env_text_handles_windows_editor_output():
    text = (
        "# comment\r\n"
        "\r\n"
        "ATLASSIAN=abc=def\r\n"
        'ANTHROPIC="quoted value"\r\n'
        "export ANTHROPIC_ADMIN='single'\r\n"
        "NOEQUALS\r\n"
        "TOKEN_WITH_HASH=abc#123\r\n"
    )
    parsed = s.parse_env_text(text)
    assert parsed == {
        "ATLASSIAN": "abc=def",
        "ANTHROPIC": "quoted value",
        "ANTHROPIC_ADMIN": "single",
        "TOKEN_WITH_HASH": "abc#123",
    }


def test_load_env_file_reads_a_bom_file_and_never_overrides(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes("﻿ATLASSIAN=from-file\r\nANTHROPIC=from-file\r\n".encode("utf-8"))
    environ = {"ANTHROPIC": "already-set"}
    loaded = s.load_env_file(env_file, environ)
    assert loaded == ["ATLASSIAN"]
    assert environ == {"ANTHROPIC": "already-set", "ATLASSIAN": "from-file"}


def test_load_env_file_missing_file_is_fine(tmp_path):
    assert s.load_env_file(tmp_path / "nope.env", {}) == []


def test_secret_never_shows_its_value():
    secret = s.Secret("sk-live-123")
    assert "sk-live-123" not in repr(secret)
    assert "sk-live-123" not in str(secret)
    assert secret.reveal() == "sk-live-123"


def test_credential_status_reports_names_only():
    status = s.credential_status({"ATLASSIAN": "x", "ANTHROPIC": "  "})
    assert status == {"ATLASSIAN": True, "BITBUCKET": False, "ANTHROPIC": False, "ANTHROPIC_ADMIN": False}


def test_redact_removes_every_secret():
    text = "failed with sk-live-123 and also tok-9"
    assert s.redact(text, ["sk-live-123", "tok-9", ""]) == "failed with *** and also ***"


def test_redact_handles_overlapping_and_duplicate_secrets():
    assert s.redact("key abcdef here", ["abc", "abcdef"]) == "key *** here"
    assert s.redact("x abc y", ["abc", "abc"]) == "x *** y"


def test_secret_values_lists_only_present_values():
    assert s.secret_values({"ATLASSIAN": "a", "OTHER": "b"}) == ["a"]


def test_settings_defaults_use_the_home_results_folder():
    settings = s.Settings.from_env({})
    assert settings.db_path == Path.home() / "github-analysis-results" / "delivery.sqlite"
    assert settings.host == "127.0.0.1"
    assert settings.overlap_hours == 2
    assert str(settings.report_tz) == "America/New_York"


def test_settings_output_dir_env_var_wins(tmp_path):
    settings = s.Settings.from_env({"GITHUB_ANALYSIS_RESULTS": str(tmp_path)})
    assert settings.db_path == tmp_path / "delivery.sqlite"


def test_secret_values_includes_the_stripped_form():
    values = s.secret_values({"ATLASSIAN": "tok-SECRET-999\r\n"})
    assert s.redact("401 for tok-SECRET-999", values) == "401 for ***"
    assert s.redact("raw tok-SECRET-999\r\n", values) == "raw ***"


def test_load_env_file_reads_utf16_with_bom(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"\xff\xfe" + "ATLASSIAN=abc\r\nANTHROPIC=def\r\n".encode("utf-16-le"))
    env = {}
    assert s.load_env_file(path, env) == ["ATLASSIAN", "ANTHROPIC"]
    assert env == {"ATLASSIAN": "abc", "ANTHROPIC": "def"}


def test_load_env_file_rejects_non_utf8_with_a_plain_message(tmp_path):
    import pytest

    path = tmp_path / ".env"
    path.write_bytes(b"ATLASSIAN=caf\xe9-secret\r\n")
    with pytest.raises(s.EnvFileError) as info:
        s.load_env_file(path, {})
    message = str(info.value)
    assert message == (
        "Could not read %s: the file is not UTF-8 or UTF-16 text. "
        "Save it as UTF-8 and try again." % path
    )
    assert "secret" not in message


def test_settings_reads_the_bitbucket_workspace_and_defaults_the_window():
    assert s.Settings.from_env({}).bitbucket_workspace == ""
    assert s.Settings.from_env({}).window_days == 90
    assert s.Settings.from_env({"BITBUCKET_WORKSPACE": " keyhealthtech "}).bitbucket_workspace == "keyhealthtech"


def test_bitbucket_is_a_known_credential_and_gets_redacted():
    assert "BITBUCKET" in s.CREDENTIAL_VARS
    assert s.secret_values({"BITBUCKET": "tok-bb-1"}) == ["tok-bb-1"]
    assert s.credential_status({"BITBUCKET": "x"})["BITBUCKET"] is True


def test_refresh_after_minutes_defaults_and_ignores_bad_values():
    assert s.Settings.from_env({}).refresh_after_minutes == 60
    assert s.Settings.from_env({"REFRESH_AFTER_MINUTES": "15"}).refresh_after_minutes == 15
    assert s.Settings.from_env({"REFRESH_AFTER_MINUTES": "soon"}).refresh_after_minutes == 60
    assert s.Settings.from_env({"REFRESH_AFTER_MINUTES": "-5"}).refresh_after_minutes == 60
