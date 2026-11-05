"""The `cohort` command: set, list and remove the people tracked for the uplift dashboard."""

from __future__ import annotations

import argparse
import sqlite3

from delivery_analysis.settings import Settings
from delivery_analysis.store import cohort
from delivery_analysis.store.db import connect, migrate


def register(commands) -> None:
    parser = commands.add_parser("cohort", help="Choose who the AI uplift dashboard tracks")
    actions = parser.add_subparsers(dest="cohort_command", metavar="<action>", required=True)
    setter = actions.add_parser("set", help="Add a person or change their level and Day 0")
    setter.add_argument("person", metavar="PERSON", help="Person id or exact display name")
    setter.add_argument("--level", required=True, help="Mid or Senior")
    setter.add_argument("--day0", required=True, metavar="YYYY-MM-DD", help="Day the person started using AI")
    actions.add_parser("list", help="Show the cohort")
    remover = actions.add_parser("remove", help="Take a person out of the cohort")
    remover.add_argument("person", metavar="PERSON", help="Person id or exact display name")


def _resolve(conn: sqlite3.Connection, text: str) -> str:
    wanted = text.strip()
    by_id = conn.execute("SELECT person_id FROM person WHERE person_id = ?", (wanted,)).fetchone()
    if by_id:
        return by_id["person_id"]
    rows = conn.execute(
        "SELECT person_id FROM person WHERE lower(display_name) = lower(?) ORDER BY person_id", (wanted,)
    ).fetchall()
    if not rows:
        raise LookupError(f"No person matches {text!r}.")
    if len(rows) > 1:
        ids = ", ".join(row["person_id"] for row in rows)
        raise ValueError(f"{text!r} matches more than one person ({ids}). Use the person id.")
    return rows[0]["person_id"]


def run(args: argparse.Namespace, settings: Settings) -> int:
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        action = args.cohort_command
        if action == "list":
            members = cohort.list_members(conn)
            if not members:
                print("The cohort is empty. Add someone with: cohort set PERSON --level Mid --day0 YYYY-MM-DD")
            for member in members:
                print(f"{member['name']}  {member['level']}  Day 0 {member['day0']}  ({member['person_id']})")
            return 0
        person_id = _resolve(conn, args.person)
        if action == "set":
            cohort.set_member(conn, person_id, args.level, args.day0)
            print(f"{person_id}: {args.level}, Day 0 {args.day0}")
            return 0
        if action == "remove":
            print("Removed." if cohort.remove_member(conn, person_id) else "Not in the cohort.")
            return 0
        raise ValueError(f"Unknown cohort action {action!r}.")
    except (ValueError, LookupError) as exc:
        print(str(exc))
        return 2
    finally:
        conn.close()
