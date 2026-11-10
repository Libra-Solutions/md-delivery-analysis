from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import uvicorn

from delivery_analysis import __version__
from delivery_analysis.app.server import create_app
from delivery_analysis.connectors.base import Connector
from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.settings import (
    CONFIG_VARS,
    CREDENTIAL_VARS,
    EnvFileError,
    Settings,
    credential_status,
    load_env_file,
    redact,
    secret_values,
)
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.store.repo_selection import detail_progress
from delivery_analysis.cli import code as code_cli
from delivery_analysis.cli import projects as projects_cli
from delivery_analysis.cli import repos as repos_cli
from delivery_analysis.cli import teams as teams_cli
from delivery_analysis.cli import tokens as tokens_cli
from delivery_analysis.sync.service import sync_and_reconcile
from github_analysis.cli.commands import COMMAND_REGISTRARS

NO_CONNECTORS_MESSAGE = (
    "No connectors are configured yet. Set BITBUCKET in .env to enable Bitbucket, ATLASSIAN and "
    "ATLASSIAN_EMAIL to enable Jira, or ANTHROPIC_ADMIN (or ANTHROPIC) to enable Claude usage "
    "(claude_code_analytics); only Confluence is still to come."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delivery-analysis",
        description=(
            "Delivery analytics: sync sources into SQLite and view them in a local app, "
            "plus the GitHub pull-request monthly report.\n\n"
            "App commands:\n"
            "  serve     Start the local web app on 127.0.0.1\n"
            "  sync      Sync configured sources into the local database\n"
            "  doctor    Show which credential variables are present (names only)\n"
            "  teams     Discover, save, import and export team rosters\n"
            "  repos     Choose which repositories are synced\n"
            "  projects  Choose which Jira projects are synced\n"
            "  code      Clone repositories and build code-weighted impact\n\n"
            "GitHub report commands (need GitHub CLI `gh` authenticated with read access):\n"
            "  analyze   Fetch data from GitHub and write TSV reports\n"
            "  export    Convert TSV reports to Excel\n"
            "  run       Analyze + export in one step\n\n"
            "Run `delivery-analysis <command> --help` for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=False)

    serve = commands.add_parser("serve", help="Start the local web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8000, help="Port to listen on (default 8000)")
    serve.add_argument("--no-browser", action="store_true", help="Do not open the browser")

    sync = commands.add_parser("sync", help="Sync configured sources into the local database")
    sync.add_argument("--source", help="Only sync the connector with this name")

    commands.add_parser("doctor", help="Show which credential variables are present (names only)")

    for register in COMMAND_REGISTRARS:
        register(commands)
    teams_cli.register(commands)
    repos_cli.register(commands)
    projects_cli.register(commands)
    tokens_cli.register(commands)
    code_cli.register(commands)
    return parser


def _serve(args: argparse.Namespace, settings: Settings, environ: Dict[str, str]) -> int:
    app = create_app(
        settings.db_path, settings=settings, environ=environ, port=args.port, public_hosts=settings.public_hosts
    )
    url = f"http://{settings.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    scope = "also https://" + ", https://".join(settings.public_hosts) if settings.public_hosts else "local only"
    print(f"Serving on {url} ({scope}). Press Ctrl+C to stop.")
    uvicorn.run(app, host=settings.host, port=args.port, log_level="info")
    return 0


def _sync(
    args: argparse.Namespace,
    settings: Settings,
    environ: Dict[str, str],
    connectors: Optional[List[Connector]],
    transport: Optional[httpx.BaseTransport] = None,
) -> int:
    active = connectors if connectors is not None else build_connectors(settings, environ, transport)
    if not active:
        print(NO_CONNECTORS_MESSAGE)
        return 0
    names = [connector.name for connector in active]
    if args.source and args.source not in names:
        print(f"No connector named {args.source!r}. Available: {', '.join(names)}")
        return 2
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        results, lines, failed_teams = sync_and_reconcile(
            conn, active, settings, environ, only=args.source, log=print
        )
        if not results:
            print(
                "Nothing to sync: no repositories are selected. "
                "Run: delivery-analysis repos add bitbucket:<workspace>/<repo>"
            )
        for result in results:
            if result.connector == "bitbucket" and result.status == "ok":
                done, total = detail_progress(conn, result.scope)
                print(f"  pull request detail: {done} of {total}")
        for line in lines:
            print(line)
    finally:
        conn.close()
    failed_sources = any(result.status == "failed" for result in results)
    return 1 if (failed_sources or failed_teams) else 0


def default_env_path() -> Path:
    """The repo's .env when running from a checkout, otherwise `.env` in the current folder."""
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file():
        return root / ".env"
    return Path.cwd() / ".env"


def _doctor(
    settings: Settings,
    environ: Dict[str, str],
    env_path: Path,
    connectors: Optional[List[Connector]],
    transport: Optional[httpx.BaseTransport] = None,
) -> int:
    print(f".env: {env_path} ({'found' if env_path.is_file() else 'not found'})")
    for name, present in credential_status(environ, CREDENTIAL_VARS + CONFIG_VARS).items():
        print(f"{name}: {'present' if present else 'missing'}")
    secrets = secret_values(environ)
    active = connectors if connectors is not None else build_connectors(settings, environ, transport)
    for connector in active:
        try:
            problems = connector.validate()
            status = "; ".join(problems) if problems else "ready"
        except Exception as exc:
            status = str(exc) or exc.__class__.__name__
        print(f"{connector.name}: {redact(status, secrets)}")
    print(f"Database: {settings.db_path}")
    return 0


def main(
    argv: Optional[List[str]] = None,
    *,
    env_path: Optional[Path] = None,
    environ: Optional[Dict[str, str]] = None,
    connectors: Optional[List[Connector]] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    legacy_handler = getattr(args, "handler", None)
    if legacy_handler is not None:
        # analyze / export / run: the GitHub report commands keep their own behavior.
        return int(legacy_handler(args))
    env = os.environ if environ is None else environ
    path = default_env_path() if env_path is None else env_path
    env_error = False
    try:
        load_env_file(path, env)
    except EnvFileError as exc:
        print(str(exc), file=sys.stderr)
        if args.command != "doctor":
            return 2
        env_error = True
    settings = Settings.from_env(env)
    if args.command == "teams":
        return teams_cli.run(args, settings)
    if args.command == "repos":
        return repos_cli.run(args, settings, env, transport=transport)
    if args.command == "projects":
        return projects_cli.run(args, settings, env, transport=transport)
    if args.command == "tokens":
        return tokens_cli.run(args, settings)
    if args.command == "code":
        return code_cli.run(args, settings, env)
    if args.command == "serve":
        return _serve(args, settings, env)
    if args.command == "sync":
        return _sync(args, settings, env, connectors, transport)
    code = _doctor(settings, env, path, connectors, transport)
    return 1 if env_error else code


if __name__ == "__main__":
    raise SystemExit(main())
