"""Clone or fetch a Bitbucket repository locally; the credential reaches git only through the environment."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from delivery_analysis.settings import redact

DEFAULT_USER = "x-bitbucket-api-token-auth"
ACCESS_TOKEN_USER = "x-token-auth"  # repository, project and workspace access tokens (prefix ATCTT)
FETCH_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"


class CodeError(RuntimeError):
    """A git step failed; the message is already redacted."""


@dataclass(frozen=True)
class CloneResult:
    path: Path
    head_sha: str
    fetched: bool


def repo_dir(results_dir: Path, repository_id: str) -> Path:
    return Path(results_dir) / "code" / repository_id.strip("{}")


def basic_header(token: str) -> str:
    """Base64 of the Basic credentials: `email:token` as given, else the bare token with the user its type needs."""
    token = token.strip()
    user = ACCESS_TOKEN_USER if token.startswith("ATCTT") else DEFAULT_USER
    pair = token if ":" in token else "%s:%s" % (user, token)
    return base64.b64encode(pair.encode("utf-8")).decode("ascii")


def git_env(token: str, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = dict(os.environ if base is None else base)
    env["GIT_CONFIG_COUNT"] = "2"
    env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
    env["GIT_CONFIG_VALUE_0"] = "Authorization: Basic " + basic_header(token)
    env["GIT_CONFIG_KEY_1"] = "core.longpaths"  # deep paths exceed Windows' 260-character limit
    env["GIT_CONFIG_VALUE_1"] = "true"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _secrets(token: str) -> List[str]:
    return [token, token.strip(), basic_header(token), "Authorization: Basic " + basic_header(token)]


def _git(
    argv: List[str], env: Dict[str, str], token: str, run: Callable[..., Any]
) -> "subprocess.CompletedProcess[str]":
    try:
        proc = run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError:
        raise CodeError("git is not installed or not on PATH")
    except OSError as exc:
        raise CodeError(redact("could not run git: %s" % exc, _secrets(token)))
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip()
        step = argv[1] if len(argv) > 1 else "git"
        raise CodeError(redact("git %s failed: %s" % (step, detail), _secrets(token)))
    return proc


def _remote_default_ref(dest: Path, env: Dict[str, str], token: str, run: Callable[..., Any]) -> Optional[str]:
    """The remote default branch as a ref, from origin/HEAD (refreshed when possible), else origin/main or origin/master."""
    base = ["git", "-C", str(dest)]
    try:
        _git(base + ["remote", "set-head", "origin", "--auto"], env, token, run)
    except CodeError:
        pass
    try:
        out = _git(base + ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], env, token, run)
        ref = (out.stdout or "").strip()
        if ref:
            return ref
    except CodeError:
        pass
    for name in ("main", "master"):
        ref = "refs/remotes/origin/" + name
        try:
            _git(base + ["rev-parse", "--verify", "--quiet", ref + "^{commit}"], env, token, run)
            return ref
        except CodeError:
            continue
    return None


def _checkout_remote_default(dest: Path, env: Dict[str, str], token: str, run: Callable[..., Any]) -> None:
    """Move our own clone's HEAD, index and files to the remote default branch."""
    ref = _remote_default_ref(dest, env, token, run)
    if ref:
        _git(["git", "-C", str(dest), "reset", "--hard", "--quiet", ref], env, token, run)


def ensure_clone(
    url: str, dest: Path, token: str, *, run: Callable[..., Any] = subprocess.run
) -> CloneResult:
    dest = Path(dest)
    env = git_env(token)
    fetched = (dest / ".git").is_dir()
    if fetched:
        _git(["git", "-C", str(dest), "fetch", "--prune", "--no-tags", "origin", FETCH_REFSPEC], env, token, run)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            _git(["git", "clone", "--no-tags", "--quiet", url, str(dest)], env, token, run)
        except CodeError:
            shutil.rmtree(dest, ignore_errors=True)
            raise
    _checkout_remote_default(dest, env, token, run)
    head = _git(["git", "-C", str(dest), "rev-parse", "HEAD"], env, token, run)
    return CloneResult(path=dest, head_sha=(head.stdout or "").strip(), fetched=fetched)
