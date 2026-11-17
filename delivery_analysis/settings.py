from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

OUTPUT_DIR_ENV_VAR = "GITHUB_ANALYSIS_RESULTS"
DEFAULT_OUTPUT_DIR = Path.home() / "github-analysis-results"
DB_FILE_NAME = "delivery.sqlite"
CREDENTIAL_VARS = ("ATLASSIAN", "BITBUCKET", "ANTHROPIC", "ANTHROPIC_ADMIN")

# Names shown by `doctor` that are configuration, not secrets (never redacted).
CONFIG_VARS = ("ATLASSIAN_EMAIL",)


def parse_env_text(text: str) -> Dict[str, str]:
    """Parse KEY=VALUE lines. Handles comments, blanks, CRLF, `export `, and quoted values."""
    values: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            values[name] = value
    return values


class EnvFileError(ValueError):
    """The .env file exists but cannot be decoded. The message never contains file contents."""


def _decode_env_bytes(data: bytes, path: Path) -> str:
    try:
        if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise EnvFileError(
            "Could not read %s: the file is not UTF-8 or UTF-16 text. "
            "Save it as UTF-8 and try again." % path
        ) from None


def load_env_file(path: Path, environ: Optional[Dict[str, str]] = None) -> List[str]:
    """Load a .env file into environ without overriding variables already set.

    Returns the names that were loaded, never their values.
    """
    target = os.environ if environ is None else environ
    if not path.is_file():
        return []
    loaded: List[str] = []
    for name, value in parse_env_text(_decode_env_bytes(path.read_bytes(), path)).items():
        if name not in target:
            target[name] = value
            loaded.append(name)
    return loaded


class Secret:
    """Holds a credential so that printing or logging it shows no value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__


def credential_status(
    environ: Optional[Mapping[str, str]] = None,
    names: Iterable[str] = CREDENTIAL_VARS,
) -> Dict[str, bool]:
    env = os.environ if environ is None else environ
    return {name: bool((env.get(name) or "").strip()) for name in names}


def secret_values(
    environ: Optional[Mapping[str, str]] = None,
    names: Iterable[str] = CREDENTIAL_VARS,
) -> List[str]:
    env = os.environ if environ is None else environ
    found: List[str] = []
    for name in names:
        raw = env.get(name) or ""
        if not raw.strip():
            continue
        for value in (raw, raw.strip()):
            if value not in found:
                found.append(value)
    return found


def redact(text: str, secrets: Iterable[str]) -> str:
    # Longest first so a secret that contains another cannot leave its tail behind.
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int((env.get(name) or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Settings:
    db_path: Path
    report_tz: ZoneInfo = ZoneInfo("America/New_York")
    overlap_days: int = 7
    host: str = "127.0.0.1"
    # Hostnames the app answers on besides localhost, over https only (for hosting behind a TLS proxy).
    public_hosts: Tuple[str, ...] = ()
    window_days: int = 90
    bitbucket_workspace: str = ""
    refresh_after_minutes: int = 60

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if environ is None else environ
        raw = (env.get(OUTPUT_DIR_ENV_VAR) or "").strip()
        base = Path(os.path.expanduser(raw)) if raw else DEFAULT_OUTPUT_DIR
        return cls(
            db_path=base / DB_FILE_NAME,
            host=(env.get("BIND_HOST") or "").strip() or "127.0.0.1",
            public_hosts=tuple(
                h.strip().lower() for h in (env.get("PUBLIC_HOSTS") or "").split(",") if h.strip()
            ),
            bitbucket_workspace=(env.get("BITBUCKET_WORKSPACE") or "").strip(),
            refresh_after_minutes=_int_env(env, "REFRESH_AFTER_MINUTES", 60),
        )
