from __future__ import annotations

import re
from datetime import datetime, timezone, tzinfo
from typing import Sequence

_PROJECT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def jql_date(since_utc: str, tz: tzinfo) -> str:
    """A UTC `YYYY-MM-DDTHH:MM:SSZ` instant as Jira's `yyyy/MM/dd HH:mm` in the profile time zone.

    Converting from UTC always gives a local time that exists, so a DST gap cannot occur; the
    repeated hour at fall-back is absorbed by the runner's 2-hour overlap. Seconds are dropped.
    """
    moment = datetime.strptime(since_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime("%Y/%m/%d %H:%M")


ACCOUNT_ID = re.compile(r"^[A-Za-z0-9:_-]+$")
_CUSTOM_FIELD = re.compile(r"^customfield_(\d+)$")


def developer_jql(
    dev_field_ids: Sequence[str],
    account_ids: Sequence[str],
    selected_keys: Sequence[str],
    since_utc: str,
    tz: tzinfo,
) -> str:
    """Issues whose Dev user fields hold a listed account, outside the selected projects."""
    if not dev_field_ids or not account_ids or not selected_keys:
        raise ValueError("Developer JQL needs Dev fields, account ids and selected project keys.")
    numbers = []
    for field_id in dev_field_ids:
        found = _CUSTOM_FIELD.match(field_id or "")
        if not found:
            raise ValueError(f"{field_id!r} is not a valid custom field id.")
        numbers.append(found.group(1))
    for account in account_ids:
        if not ACCOUNT_ID.match(account or ""):
            raise ValueError(f"{account!r} is not a valid account id.")
    for key in selected_keys:
        if not _PROJECT_KEY.match(key or ""):
            raise ValueError(f"{key!r} is not a valid project key.")
    accounts = ", ".join(f'"{account}"' for account in account_ids)
    clauses = " OR ".join(f"cf[{number}] in ({accounts})" for number in numbers)
    keys = ", ".join(f'"{key}"' for key in selected_keys)
    return (
        f'({clauses}) AND project not in ({keys}) AND updated >= "{jql_date(since_utc, tz)}" '
        "ORDER BY updated ASC, key ASC"
    )


def project_jql(project_key: str, since_utc: str, tz: tzinfo) -> str:
    if not _PROJECT_KEY.match(project_key or ""):
        raise ValueError(f"{project_key!r} is not a valid project key.")
    return (
        f'project = "{project_key}" AND updated >= "{jql_date(since_utc, tz)}" '
        "ORDER BY updated ASC, key ASC"
    )
