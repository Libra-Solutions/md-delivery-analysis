"""The `backfill` command: pull Jira and Bitbucket history further back than the usual window."""

from __future__ import annotations

import argparse

from delivery_analysis.settings import redact, secret_values
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.sync.backfill import backfill


def register(commands) -> None:
    parser = commands.add_parser(
        "backfill", help="Re-fetch Jira and Bitbucket history further back than the normal window"
    )
    parser.add_argument("--days", type=int, default=450, help="How far back to fetch, 1 to 3650 (default 450)")
    parser.add_argument("--only", metavar="SOURCE", help="Only this source, for example jira or bitbucket")
    parser.add_argument("--force", action="store_true",
                        help="Fetch history again even where it is already stored")
    parser.add_argument("--budget", type=int, metavar="N",
                        help="Bitbucket requests for this run (default BITBUCKET_BUDGET or 900); "
                             "about 4 per pull request detail")
    parser.add_argument("--until-done", action="store_true",
                        help="No request budget: wait out Bitbucket rate limits and keep going until done")
    parser.add_argument("--max-hours", type=float, default=8.0, metavar="H",
                        help="With --until-done, stop after this many hours (default 8); the rest carries over")


def run(args: argparse.Namespace, settings, environ: dict, transport=None) -> int:
    secrets = secret_values(environ)
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        try:
            results, _notices, failed_teams = backfill(
                conn, settings, environ, args.days, only=args.only, log=lambda line: print(redact(line, secrets)), transport=transport,
                force=getattr(args, "force", False), budget=getattr(args, "budget", None),
                until_done_hours=getattr(args, "max_hours", 8.0) if getattr(args, "until_done", False) else None,
            )
        except ValueError as exc:
            print(redact(str(exc), secrets))
            return 2
        except Exception as exc:
            print(redact("Backfill failed: " + (str(exc) or exc.__class__.__name__), secrets))
            return 1
        failed = [r for r in results if getattr(r, "status", "") == "failed"]
        return 1 if failed or failed_teams else 0
    finally:
        conn.close()
